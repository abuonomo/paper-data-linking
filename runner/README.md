# Standalone batch runner (`pdl-batch`)

Runs the whole paper pipeline (paper analysis, structuring, instrument grounding, normalization) on a machine with GPUs and nothing else: paper text in as files, results out as files. It needs no database, queue or network access. It starts one vLLM server per GPU and keeps every GPU busy; the same command works on 1, 2 or 8 GPUs.

The image is `ghcr.io/abuonomo/paper-data-linking/runner`. The model recipe is Gemma 4 26B-A4B (FP8) with the MTP drafter on vLLM v0.32.0, as measured on NVIDIA L40S.

## What you need

| | |
|---|---|
| Paper text | A directory of `.jsonl` or `.jsonl.gz` files, one paper per line: `{"bibcode": "...", "text": "..."}`. Extra keys are carried through to the results. |
| Model weights | A Hugging Face cache directory holding `RedHatAI/gemma-4-26B-A4B-it-FP8-dynamic` and `google/gemma-4-26B-A4B-it-assistant`. The servers run offline and never download. |
| Catalog snapshot | One JSON file with the instrument catalog, supplied with the image release. |
| GPUs | One or more with about 45 GB of memory each (L40S). Docker with the NVIDIA container toolkit. |

## Run it

```bash
docker run --rm --gpus all --ipc=host --network none \
  -v /path/to/papers:/data/papers:ro \
  -v /path/to/out:/data/out \
  -v /path/to/catalog_snapshot.json:/data/catalog.json:ro -e PDL_CATALOG_SNAPSHOT=/data/catalog.json \
  -v /path/to/hf-cache:/root/.cache/huggingface \
  ghcr.io/abuonomo/paper-data-linking/runner all
```

Or with `runner/compose.yaml`: set `PAPERS_DIR`, `OUT_DIR`, `CATALOG` and `HF_CACHE`, then `docker compose -f runner/compose.yaml up`.

`all` finds the free GPUs, starts a vLLM server on each (logs in `out/logs/`), waits for them to load, processes every paper, and shuts the servers down. A progress line is printed every 30 seconds:

```
[pdl-batch] done 1188 failed 0 in-flight 512 | 0.3% of 420000 | 1630 papers/hr, about 10d16h left | calls 96211 tok in/out 280.4M/61.9M | oldest 2019ApJ...880..116K 14m | ep0 run 41 wait 0 kv 88% held 12 budget 790k | ...
```

- `done`, `failed` and `in-flight` count papers in this run. The percentage is of the whole input, including papers finished by earlier runs into the same output directory.
- The rate is papers finished over the last 15 minutes, and the time left is the remaining papers at that rate. Neither means much until the first papers have gone all the way through.
- `calls` and the token counts include papers still in flight.
- `oldest` is the paper that has been in flight longest. A paper with many instruments can take tens of minutes; one whose age keeps growing while the servers sit idle is stuck.
- Per server: requests it is running and has queued, how full its KV cache is, then the runner's own calls held back and its current admission budget in tokens.

The total comes from counting the input while the run starts, so it appears a little after the first line on a large input. `--total N` gives it directly.

**Stopping and resuming.** Stop it any way you like (Ctrl-C, `docker stop`, a killed job). Run the same command again with the same output directory and it continues: finished papers are skipped, and papers that were in flight keep their step-1 answer and redo only the rest. Exit code 0 means every paper is settled; 3 means some are unfinished and a rerun will finish them.

On the first SIGTERM or Ctrl-C the runner starts no new papers and gives the ones in flight up to 120 seconds to finish; a second one stops at once. Two things shorten that, and neither loses work:

- `docker stop` kills the container after 10 seconds unless told otherwise. Use `docker stop -t 150` to let papers in flight finish (`runner/compose.yaml` already sets this).
- A signal sent to every process at once (`timeout`, a job scheduler cancelling the job) stops the vLLM servers along with the runner, so papers in flight cannot finish and are left for the next run.

**Check first.** `doctor` verifies the configuration, catalog, paper source and (for existing servers) that the model answers:

```bash
docker run --rm ... ghcr.io/abuonomo/paper-data-linking/runner doctor --papers /data/papers --endpoints http://host:8000
```

## Try it without GPUs

`--fake-gpus N` starts N built-in stand-in servers in place of vLLM. They return canned answers in the right formats, so this exercises everything except the model: reading papers, scheduling across N endpoints, retries, resume, output files and export.

```bash
docker run --rm --network none \
  -v /path/to/papers:/data/papers:ro -v /path/to/out:/data/out \
  -v /path/to/catalog_snapshot.json:/data/catalog.json:ro -e PDL_CATALOG_SNAPSHOT=/data/catalog.json \
  ghcr.io/abuonomo/paper-data-linking/runner all --fake-gpus 8
```

A CPU-only image for this (no vLLM inside, a few hundred MB) builds with `docker build -f runner/Dockerfile --build-arg BASE_IMAGE=python:3.11-slim -t pdl-runner:cpu .`

## Output

Everything is under the output directory, as append-only JSON lines, one file per worker:

| Path | Contents |
|---|---|
| `results/` | One line per finished paper: the step-1 form, the structured form, the normalized result (grounded instruments, time windows, parameters, quotes), token counts, and the catalog, prompt and runner versions that produced it. |
| `failures/` | Papers that will not be retried, with a reason (`empty_text`, `text_too_long`, `context_too_long`, `step1_broken`, `endpoint_down`, ...). `--retry-failed` processes them again. |
| `step1/` | Step-1 answers, kept so an interrupted paper does not regenerate them. |
| `calls/` | One line per model call. `--call-log meta` (default) records sizes and timings; `full` adds prompts and answers, gzipped; `off` disables it. |
| `logs/` | vLLM server logs. |
| `index/` | One short line per record in `results/`, `step1/` and `failures/`, so that resuming and `status` do not have to read every result. It is rebuilt from those directories when missing or behind, and can be deleted. |
| `progress.json`, `runs.jsonl` | The last progress report (rewritten every 30 seconds, for anything that wants to poll the run) and a record of each run. |

`pdl-batch status` summarizes a directory: results and failures on disk, failures by reason, and the last progress report. It can be run while a run is going.

**Results contain text from the papers** (quotes, summaries). Nothing leaves the machine unless you export it:

```bash
pdl-batch export --level tuples   --to tuples.jsonl     # bibcode, data system, mission, instrument, time window
pdl-batch export --level redacted --to redacted.jsonl   # + normalized parameters; no quotes, comments or free text
pdl-batch export --level full     --to full.jsonl       # result lines as written
```

`--allowlist file` restricts any export to the listed bibcodes, for example the permissively licensed ones.

## Other ways to run

**Your own vLLM servers.** `run` processes papers against endpoints that already exist, and needs no GPU in its own container. This is the mode for a site that runs vLLM natively or on other hosts.

```bash
pdl-batch run --endpoints http://gpu-node:8000,http://gpu-node:8001 --papers /data/papers --out /data/out
```

Start those servers with the flags this image uses (`pdl-batch serve` starts them without processing anything, and prints the command lines to `logs/`). The ones that matter for correctness: `--reasoning-parser gemma4` (answers must not contain the thinking text) and a context of at least 160k tokens.

**Without Docker.** The runner is plain Python 3.11. From the repository root: `uv sync --only-group runner --no-install-project`, then `.venv/bin/python -m paper_data_linking.runner.cli run ...`.

**Your own text store.** If papers are not in files, write a small class with one method, `iter_papers()`, and pass it as `--source package.module:factory`. `runner/example_source.py` is a template. An optional second method, `iter_ids()`, lets the runner count the papers for the percent done and time left.

**Several machines.** `--shard 0/2` on one node and `--shard 1/2` on another split the same input by bibcode. They can share an output directory.

## Settings

Every option has a `PDL_*` environment variable; `pdl-batch <command> --help` lists them. The ones most likely to matter:

| Option | Default | |
|---|---|---|
| `--gpus` / `PDL_GPUS` | every free GPU | GPU indices to use. GPUs with more than 10% of memory already in use are skipped unless `--include-busy-gpus`. |
| `--papers-in-flight` | 128 | Papers processed at once per GPU. |
| `--kv-tokens` | read from the server | KV-cache capacity per GPU in tokens. It sets where admission starts: calls are admitted against a token budget of 85% of it, which is what keeps long step-1 prompts from overcommitting memory. |
| `--budget-fraction` | 0.85 | How full to keep each server's KV cache. Every 10 seconds the budget is raised if calls are being held back while the cache is under this, and lowered if the cache is over it, so a wrong capacity figure corrects itself. `--fixed-budget` turns the adjustment off. |
| `--drafter` / `PDL_DRAFTER` | the Gemma 4 MTP drafter | Empty string turns speculative decoding off. |
| `--patience` | 900 s | How long to keep retrying a server that stopped answering before its papers are handed to another server. |
| `PDL_VLLM_EXTRA_ARGS` | | Extra flags appended to every `vllm serve`. |

## How it behaves

- **One vLLM server per GPU**, not one tensor-parallel server across GPUs. On L40S a 4-GPU tensor-parallel server measured about 140 papers/hour per GPU against about 500 for single-GPU servers on step 1.
- **One worker process per server**, each running one paper per thread from first call to last. Workers pull from a shared queue, so a faster server takes more papers.
- **A dead server is not a result.** If a server stops answering, calls are retried; if it stays down, its papers are returned to the queue for the other servers, and a restarted server rejoins. A paper is written to `results/` only if the model answered every one of its calls.
- **Step-1 answers are checked.** An empty, truncated or looping answer is asked again, up to three times, then recorded as `step1_broken`. Answers that open with `---` are cut off there (the model tends to loop after it) and come back empty; if that happens every time, the third attempt runs without the cut-off.
- **An answer lost to reasoning is asked again.** If a call spends its whole token limit on reasoning and returns no answer, it is sampled again, up to twice, before the pipeline sees it.

## What has and has not been measured

Measured with this runner on one L40S (`all`, networking disabled, 182 evaluation papers, 2026-11-15):

- 180 papers finished and 2 were recorded as `step1_broken`. Against a human-reviewed reference set, result quality matched the older database-driven path on the same papers.
- With the GPU full the server generated about 2,300 tokens/second across about 75 concurrent calls, with the KV cache above 90% and no preemption.
- These papers cost about 64,000 generated tokens each (57,000 of them downstream; mission identification alone is 40%). At the full-GPU rate that is about 130 papers/hour for a set where nearly every paper names instruments.
- The run itself took 124 minutes (88 papers/hour). That figure understates steady state: with 128 papers in flight, a 182-paper run is mostly start-up and drain, and the GPU was full for only 30 of those minutes.

Step 1 alone runs at about 500 papers/hour (7 GPU-seconds per paper). Downstream costs about 25 GPU-seconds on a paper that names instruments. That gives about 180 to 260 papers/hour per GPU if a quarter to half of the papers name instruments. The evaluation papers name more instruments than typical papers (4.6 on average), so this is probably conservative.

Verified without GPUs: the full path against stand-in servers, including 8 endpoints, a killed run resumed with every paper processed exactly once, a dead endpoint, and a container with networking disabled.

Not yet measured: more than one GPU, a run long enough to reach steady state, and a restart against real vLLM. The budget adjustment, the step-1 attempt without the cut-off and the re-sampling of answers lost to reasoning were added after that run and have only been tested against stand-in servers. In that run the server's metrics gave two thirds of its real KV capacity, so the first 18 minutes ran 20 step-1 calls at a time at 45% KV use.
