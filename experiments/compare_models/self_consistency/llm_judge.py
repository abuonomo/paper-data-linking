"""
LLM-as-Judge Evaluation for Cross-Model Disagreements.

Uses a third LLM (Claude Opus 4.5 via Bedrock) to adjudicate cases where
GPT-5 and Bedrock GPT-OSS-120B disagree.

Methodology:
- Extract disagreement cases (cross_model_agreement < 1.0)
- Present each case with blinded answers (Answer A / Answer B)
- Randomize presentation order to avoid position bias
- Ask judge to evaluate which answer is more correct
- Tally results and output statistics
"""

import json
import random
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import litellm
from tqdm import tqdm

# Configure paths
VIZ_DATA_DIR = Path(__file__).parent / "viz" / "data"
RESULTS_DIR = Path(__file__).parent / "judge_results"

# Model configuration options
JUDGE_MODELS = {
    # Bedrock Claude options (requires valid AWS credentials)
    "bedrock-claude-opus": "bedrock/converse/anthropic.claude-opus-4-5-20251101-v1:0",
    "bedrock-claude-sonnet": "bedrock/converse/anthropic.claude-3-5-sonnet-20241022-v2:0",
    # OpenAI options (requires OPENAI_API_KEY)
    "openai-gpt4": "openai/gpt-4-turbo",
    "openai-gpt4o": "openai/gpt-4o",
    "openai-gpt5": "openai/gpt-5.2",
    # Anthropic direct (requires ANTHROPIC_API_KEY)
    "claude-sonnet": "anthropic/claude-sonnet-4-20250514",
    "claude-opus": "anthropic/claude-opus-4-20250514",
}

DEFAULT_JUDGE = "claude-sonnet"  # Default to direct Anthropic API
AWS_REGION = "us-east-1"

# Models being compared
MODEL_A = "openai/gpt-5"
MODEL_B = "bedrock/openai.gpt-oss-120b-1:0"


@dataclass
class JudgmentResult:
    """Result from judging a single case."""
    case_id: str
    call_type: str
    winner: str  # "A", "B", "tie", "neither", "error"
    reasoning: str
    model_a: str  # Which actual model was Answer A
    model_b: str  # Which actual model was Answer B
    answer_a: str  # The actual answer presented as A
    answer_b: str  # The actual answer presented as B
    raw_response: str
    cross_model_agreement: float

    def actual_winner(self) -> str:
        """Return the actual winning model name, or the verdict."""
        if self.winner == "A":
            return self.model_a
        elif self.winner == "B":
            return self.model_b
        return self.winner


@dataclass
class EvaluationStats:
    """Statistics from evaluating multiple cases."""
    total_cases: int = 0
    model_a_wins: int = 0  # GPT-5 wins
    model_b_wins: int = 0  # Bedrock wins
    ties: int = 0
    neither: int = 0
    errors: int = 0
    judgments: list = field(default_factory=list)

    def summary(self) -> str:
        """Return a summary string."""
        lines = [
            f"Total cases judged: {self.total_cases}",
            f"  {MODEL_A}: {self.model_a_wins} wins ({100*self.model_a_wins/max(1,self.total_cases):.1f}%)",
            f"  {MODEL_B}: {self.model_b_wins} wins ({100*self.model_b_wins/max(1,self.total_cases):.1f}%)",
            f"  Ties: {self.ties} ({100*self.ties/max(1,self.total_cases):.1f}%)",
            f"  Neither correct: {self.neither} ({100*self.neither/max(1,self.total_cases):.1f}%)",
            f"  Errors: {self.errors}",
        ]
        return "\n".join(lines)


def load_disagreement_cases(
    call_type: str,
    agreement_threshold: float = 0.5,
    exclude_null_pairs: bool = True,
) -> list[dict]:
    """
    Load cases where models disagree.

    Args:
        call_type: The call type to load (e.g., 'mission_identification')
        agreement_threshold: Cases with cross_model_agreement below this are disagreements
        exclude_null_pairs: If True, exclude cases where both models gave null responses

    Returns:
        List of case data dictionaries
    """
    cases_file = VIZ_DATA_DIR / call_type / "cases.json"
    if not cases_file.exists():
        raise FileNotFoundError(f"Cases file not found: {cases_file}")

    with open(cases_file) as f:
        data = json.load(f)

    disagreement_cases = []
    for case in data["cases"]:
        # Filter by agreement threshold
        if case.get("cross_model_agreement", 1.0) >= agreement_threshold:
            continue

        # Load full case detail
        case_detail_file = VIZ_DATA_DIR / call_type / "cases" / f"{case['case_id']}.json"
        if not case_detail_file.exists():
            continue

        with open(case_detail_file) as f:
            case_detail = json.load(f)

        # Check for null pairs if excluding
        if exclude_null_pairs:
            model_a_data = case_detail.get("models", {}).get(MODEL_A, {})
            model_b_data = case_detail.get("models", {}).get(MODEL_B, {})

            # Check if majority responses exist and are not null
            model_a_null = not model_a_data.get("majority_response") or model_a_data.get("null_rate", 0) >= 0.5
            model_b_null = not model_b_data.get("majority_response") or model_b_data.get("null_rate", 0) >= 0.5

            if model_a_null and model_b_null:
                continue

        disagreement_cases.append(case_detail)

    return disagreement_cases


def create_judge_prompt(
    case: dict,
    call_type: str,
    randomize_order: bool = True,
) -> tuple[str, str, str, str, str]:
    """
    Create a prompt for the judge LLM.

    Returns:
        Tuple of (prompt, model_a_name, model_b_name, answer_a, answer_b)
    """
    # Extract the input (system + user prompts)
    input_messages = case.get("input_messages", [])
    system_prompt = ""
    user_prompt = ""
    for msg in input_messages:
        if msg["role"] == "system":
            system_prompt = msg["content"]
        elif msg["role"] == "user":
            user_prompt = msg["content"]

    # Get model outputs (use majority response or first run)
    models_data = case.get("models", {})

    model_a_data = models_data.get(MODEL_A, {})
    model_b_data = models_data.get(MODEL_B, {})

    # Get the actual outputs - prefer majority_response, fall back to first run
    answer_gpt5 = model_a_data.get("majority_response", [])
    if isinstance(answer_gpt5, list):
        answer_gpt5 = ", ".join(str(x) for x in answer_gpt5) if answer_gpt5 else "UNKNOWN"

    answer_bedrock = model_b_data.get("majority_response", [])
    if isinstance(answer_bedrock, list):
        answer_bedrock = ", ".join(str(x) for x in answer_bedrock) if answer_bedrock else "UNKNOWN"

    # Randomly assign which model is A vs B
    if randomize_order and random.random() < 0.5:
        answer_a, answer_b = answer_bedrock, answer_gpt5
        model_a_name, model_b_name = MODEL_B, MODEL_A
    else:
        answer_a, answer_b = answer_gpt5, answer_bedrock
        model_a_name, model_b_name = MODEL_A, MODEL_B

    # Build the judge prompt
    # Note: We include full prompts so the judge can properly evaluate answers
    # (e.g., mission_identification includes a list of 361 missions that must be visible)

    # Call-type specific evaluation guidance
    call_type_guidance = ""
    if call_type == "mission_identification":
        call_type_guidance = """
## CRITICAL INSTRUCTION-FOLLOWING CHECK

The system prompt EXPLICITLY instructs models to:
- "Return the numbers (1-N) of the top 10 most likely missions, comma-separated"
- Example format: '15,3,42,7,23,1,56,89,12,4'

**A response that returns only 1-3 items when 10 were requested is NOT following instructions.**
This is a serious failure that should heavily penalize that answer, even if the single item happens to be correct.
Instruction-following is a primary evaluation criterion.
"""
    elif call_type == "mission_selection":
        call_type_guidance = """
## OUTPUT FORMAT CHECK

For mission_selection tasks, check whether the model followed the output format specified in the instructions.
If multiple valid missions exist, returning all of them is correct behavior.
"""
    elif call_type == "instrument_selection":
        call_type_guidance = """
## OUTPUT FORMAT CHECK

For instrument_selection tasks, check whether the model followed the output format specified in the instructions.
If multiple valid instruments exist (e.g., same instrument on multiple spacecraft), returning all of them is correct behavior.
Returning "0" when the instrument IS clearly in the list is incorrect.
"""

    prompt = f"""You are an expert evaluator for heliophysics data extraction tasks. Your job is to judge which of two AI model responses better answers the given task.

## Task Context

The task type is: {call_type}
{call_type_guidance}
### System Instructions Given to Models:
{system_prompt}

### User Query:
{user_prompt}

## Model Responses

**Answer A:** {answer_a}

**Answer B:** {answer_b}

## Your Evaluation

Carefully analyze both responses against the task requirements. Consider:
1. **Instruction Following**: Did the response follow the output format specified in the system instructions? (HIGHEST PRIORITY)
2. Correctness: Does the answer correctly identify the requested information?
3. Completeness: Does it include all relevant items without missing important ones?
4. Precision: Does it avoid including irrelevant or incorrect items?

Based on your analysis, provide your judgment in the following format:

REASONING: <Your step-by-step analysis comparing the two answers>

VERDICT: <One of: "A", "B", "TIE", "NEITHER">
- "A" if Answer A is clearly better
- "B" if Answer B is clearly better
- "TIE" if both answers are equally good (or equally bad)
- "NEITHER" if both answers are clearly wrong/unhelpful

Important: End your response with exactly one of these verdict lines:
VERDICT: A
VERDICT: B
VERDICT: TIE
VERDICT: NEITHER
"""

    return prompt, model_a_name, model_b_name, answer_a, answer_b


def parse_judge_response(response: str) -> tuple[str, str]:
    """
    Parse the judge's response to extract verdict and reasoning.

    Returns:
        Tuple of (verdict, reasoning)
    """
    verdict = "error"
    reasoning = response

    # Look for VERDICT line
    lines = response.strip().split("\n")
    for line in reversed(lines):  # Check from end
        line_upper = line.strip().upper()
        if line_upper.startswith("VERDICT:"):
            verdict_part = line_upper.replace("VERDICT:", "").strip()
            if verdict_part in ["A", "B", "TIE", "NEITHER"]:
                verdict = verdict_part.lower()
                if verdict == "tie":
                    verdict = "tie"
                elif verdict == "neither":
                    verdict = "neither"
                break

    # Extract reasoning
    if "REASONING:" in response:
        reasoning = response.split("REASONING:")[-1]
        if "VERDICT:" in reasoning:
            reasoning = reasoning.split("VERDICT:")[0]
        reasoning = reasoning.strip()

    return verdict, reasoning


def judge_case(
    case: dict,
    call_type: str,
    judge_model: str,
    verbose: bool = False,
) -> JudgmentResult:
    """
    Use the judge LLM to evaluate a single case.
    """
    prompt, model_a_name, model_b_name, answer_a, answer_b = create_judge_prompt(
        case, call_type, randomize_order=True
    )

    try:
        # Build kwargs for litellm call
        litellm_kwargs = {
            "model": judge_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,  # Deterministic for judging
        }

        # GPT-5+ models use max_completion_tokens, others use max_tokens
        if "gpt-5" in judge_model.lower():
            litellm_kwargs["max_completion_tokens"] = 2000
        else:
            litellm_kwargs["max_tokens"] = 2000

        # Add AWS region only for Bedrock models
        if "bedrock" in judge_model.lower():
            litellm_kwargs["aws_region_name"] = AWS_REGION

        response = litellm.completion(**litellm_kwargs)
        raw_response = response.choices[0].message.content
        verdict, reasoning = parse_judge_response(raw_response)

        if verbose:
            print(f"  Verdict: {verdict}")
            print(f"  Model A was: {model_a_name}")
            print(f"  Model B was: {model_b_name}")

        return JudgmentResult(
            case_id=case["case_id"],
            call_type=call_type,
            winner=verdict.upper() if verdict in ["a", "b"] else verdict,
            reasoning=reasoning,
            model_a=model_a_name,
            model_b=model_b_name,
            answer_a=answer_a,
            answer_b=answer_b,
            raw_response=raw_response,
            cross_model_agreement=case.get("cross_model_agreement", 0),
        )

    except Exception as e:
        import traceback
        error_msg = f"{type(e).__name__}: {str(e)}"
        return JudgmentResult(
            case_id=case["case_id"],
            call_type=call_type,
            winner="error",
            reasoning=error_msg,
            model_a=model_a_name,
            model_b=model_b_name,
            answer_a=answer_a,
            answer_b=answer_b,
            raw_response=traceback.format_exc(),
            cross_model_agreement=case.get("cross_model_agreement", 0),
        )


def run_evaluation(
    call_type: str,
    judge_model: Optional[str] = None,
    max_cases: Optional[int] = None,
    agreement_threshold: float = 0.5,
    exclude_null_pairs: bool = True,
    verbose: bool = True,
    save_results: bool = True,
) -> EvaluationStats:
    """
    Run the full evaluation for a call type.

    Args:
        call_type: The call type to evaluate
        judge_model: Judge model key or full model string (default: DEFAULT_JUDGE)
        max_cases: Maximum number of cases to evaluate (None = all)
        agreement_threshold: Cases with agreement below this are evaluated
        exclude_null_pairs: Skip cases where both models gave null
        verbose: Print progress
        save_results: Save results to JSON file

    Returns:
        EvaluationStats with results
    """
    # Resolve judge model
    if judge_model is None:
        judge_model = DEFAULT_JUDGE

    # Look up in JUDGE_MODELS dict, or use as-is if not found
    actual_judge_model = JUDGE_MODELS.get(judge_model, judge_model)

    if verbose:
        print(f"Judge model: {actual_judge_model}")
        print(f"Loading disagreement cases for {call_type}...")

    cases = load_disagreement_cases(
        call_type,
        agreement_threshold=agreement_threshold,
        exclude_null_pairs=exclude_null_pairs,
    )

    if max_cases:
        cases = cases[:max_cases]

    if verbose:
        print(f"Found {len(cases)} disagreement cases to evaluate")

    stats = EvaluationStats()

    # Process cases with detailed progress logging
    for i, case in enumerate(cases, 1):
        if verbose:
            print(f"\n[{i}/{len(cases)}] Case: {case['case_id'][:12]}...")

        result = judge_case(case, call_type, judge_model=actual_judge_model, verbose=False)
        stats.judgments.append(result)
        stats.total_cases += 1

        # Update counts
        actual_winner = result.actual_winner()
        if actual_winner == MODEL_A:
            stats.model_a_wins += 1
        elif actual_winner == MODEL_B:
            stats.model_b_wins += 1
        elif result.winner == "tie":
            stats.ties += 1
        elif result.winner == "neither":
            stats.neither += 1
        else:
            stats.errors += 1

        # Live progress logging
        if verbose:
            winner_display = result.winner
            if result.winner in ["A", "B"]:
                winner_display = f"{result.winner} ({actual_winner.split('/')[-1][:20]})"
            print(f"  Verdict: {winner_display}")
            print(f"  Running tally: GPT-5={stats.model_a_wins} | Bedrock={stats.model_b_wins} | Tie={stats.ties} | Neither={stats.neither} | Err={stats.errors}")

    if verbose:
        print("\n" + "="*60)
        print(f"EVALUATION RESULTS: {call_type}")
        print("="*60)
        print(stats.summary())

    if save_results:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        results_file = RESULTS_DIR / f"{call_type}_judgments.json"

        results_data = {
            "call_type": call_type,
            "model_a": MODEL_A,
            "model_b": MODEL_B,
            "judge_model": actual_judge_model,
            "agreement_threshold": agreement_threshold,
            "exclude_null_pairs": exclude_null_pairs,
            "stats": {
                "total_cases": stats.total_cases,
                "model_a_wins": stats.model_a_wins,
                "model_b_wins": stats.model_b_wins,
                "ties": stats.ties,
                "neither": stats.neither,
                "errors": stats.errors,
            },
            "judgments": [
                {
                    "case_id": j.case_id,
                    "winner": j.winner,
                    "actual_winner": j.actual_winner(),
                    "reasoning": j.reasoning,
                    "model_a": j.model_a,
                    "model_b": j.model_b,
                    "answer_a": j.answer_a,
                    "answer_b": j.answer_b,
                    "cross_model_agreement": j.cross_model_agreement,
                }
                for j in stats.judgments
            ],
        }

        with open(results_file, "w") as f:
            json.dump(results_data, f, indent=2)

        if verbose:
            print(f"\nResults saved to: {results_file}")

    return stats


def main():
    """Run evaluation on mission_identification disagreements."""
    import argparse

    parser = argparse.ArgumentParser(
        description="LLM-as-Judge evaluation for cross-model disagreements",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Available judge models:
{chr(10).join(f'  {k}: {v}' for k, v in JUDGE_MODELS.items())}

Examples:
  # Use default judge (Claude Sonnet via direct API)
  python llm_judge.py --max-cases 5

  # Use Bedrock Claude (requires valid AWS credentials)
  python llm_judge.py --judge bedrock-claude-sonnet

  # Use OpenAI GPT-4
  python llm_judge.py --judge openai-gpt4o

  # Dry run to count cases
  python llm_judge.py --dry-run
""",
    )
    parser.add_argument(
        "--call-type",
        default="mission_identification",
        help="Call type to evaluate (default: mission_identification)",
    )
    parser.add_argument(
        "--judge",
        default=DEFAULT_JUDGE,
        help=f"Judge model key or full model string (default: {DEFAULT_JUDGE})",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Maximum cases to evaluate (default: all)",
    )
    parser.add_argument(
        "--agreement-threshold",
        type=float,
        default=0.5,
        help="Cases with agreement below this are evaluated (default: 0.5)",
    )
    parser.add_argument(
        "--include-null-pairs",
        action="store_true",
        help="Include cases where both models gave null responses",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Just count cases without running evaluation",
    )
    parser.add_argument(
        "--list-judges",
        action="store_true",
        help="List available judge models and exit",
    )

    args = parser.parse_args()

    if args.list_judges:
        print("Available judge models:")
        for key, model in JUDGE_MODELS.items():
            marker = " (default)" if key == DEFAULT_JUDGE else ""
            print(f"  {key}: {model}{marker}")
        return

    if args.dry_run:
        cases = load_disagreement_cases(
            args.call_type,
            agreement_threshold=args.agreement_threshold,
            exclude_null_pairs=not args.include_null_pairs,
        )
        print(f"Found {len(cases)} disagreement cases for {args.call_type}")
        return

    run_evaluation(
        call_type=args.call_type,
        judge_model=args.judge,
        max_cases=args.max_cases,
        agreement_threshold=args.agreement_threshold,
        exclude_null_pairs=not args.include_null_pairs,
    )


if __name__ == "__main__":
    main()
