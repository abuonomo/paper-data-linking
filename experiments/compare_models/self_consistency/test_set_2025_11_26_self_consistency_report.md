# Self-Consistency Analysis: test_set_2025_11_26

**Generated**: 2026-01-09 18:07:27
**Model**: bedrock/openai.gpt-oss-120b-1:0
**Test Set**: test_set_2025_11_26
**Number of runs**: 5 (temperature=1.0)

## Summary Table

| Call Type | Cases | Perfect | High | Kappa | Cost/Run | Tokens/Run |
|-----------|-------|---------|------|-------|----------|------------|
| Cadence Normalization          | 100 |  98.0% |   2.0% | 0.995 | $0.0279 | 155,884 |
| Detector Normalization         | 100 |  97.0% |   3.0% | 0.993 | $0.0190 | 104,133 |
| Instrument Selection           | 100 |  90.0% |   8.0% | 0.970 | $0.0287 | 146,849 |
| Instrument Validation          | 100 |   0.0% |   0.0% | 0.000 | $0.0594 | 229,236 |
| Mission Identification         | 100 |  72.0% |  17.0% | 0.842 | $0.0972 | 549,850 |
| Mission Selection              | 100 |  81.0% |  10.0% | 0.900 | $0.0272 | 119,447 |
| Physobs Normalization          |  99 |  67.7% |  17.2% | 0.866 | $0.0232 | 102,978 |
| Time Normalization             |  95 |  86.3% |   6.3% | 0.939 | $0.0326 | 105,677 |
| Wavelength Normalization       | 100 |  98.0% |   0.0% | 0.975 | $0.0218 | 116,727 |

**Total cost per complete run**: $0.34
**Total tokens per complete run**: 1,630,781

## Detailed Analysis

### Cadence Normalization

- **Valid cases**: 100
- **Perfect consistency (5/5)**: 98 (98.0%)
- **High consistency (4/5)**: 2 (2.0%)
- **Moderate consistency (3/5)**: 0 (0.0%)
- **API errors**: 0
- **Parse errors**: 0

**Sample disagreements**:

1. Case 2ad4c0d1-34d8-4aa9-a804-a23c3bb86457: 2 unique responses
   - 4x: `none`
   - 1x: `pt12h`
2. Case e4a39f88-4209-4600-9726-bee13b466a4a: 2 unique responses
   - 4x: `pt0.000008s, pt0.000133s`
   - 1x: `{"original_text": ""}`

### Detector Normalization

- **Valid cases**: 100
- **Perfect consistency (5/5)**: 97 (97.0%)
- **High consistency (4/5)**: 3 (3.0%)
- **Moderate consistency (3/5)**: 0 (0.0%)
- **API errors**: 0
- **Parse errors**: 0

**Sample disagreements**:

1. Case f5cc214b-51e3-4198-9a53-dca260b1c7b8: 2 unique responses
   - 4x: `c2`
   - 1x: `uncertain`
2. Case 039b520a-575e-429d-8008-dd1a333694e9: 2 unique responses
   - 4x: `uncertain`
   - 1x: `sem`
3. Case 5ce4af38-9275-4d85-8576-234f52067938: 2 unique responses
   - 4x: `let`
   - 1x: `uncertain`

### Instrument Selection

- **Valid cases**: 100
- **Perfect consistency (5/5)**: 90 (90.0%)
- **High consistency (4/5)**: 8 (8.0%)
- **Moderate consistency (3/5)**: 2 (2.0%)
- **API errors**: 0
- **Parse errors**: 0

**Sample disagreements**:

1. Case 768a9845-d4af-4f84-b7d0-cb2e4c514f4e: 2 unique responses
   - 4x: `0`
   - 1x: `8`
2. Case 04db4599-9728-4a1b-8cc9-a7d0d2657151: 2 unique responses
   - 4x: `0`
   - 1x: `5`
3. Case 4f96a9a9-2e05-47dc-8be3-2d5428f2481c: 3 unique responses
   - 3x: `3,4,8,10,12`
   - 1x: `8`
   - 1x: `0`

### Instrument Validation

- **Valid cases**: 100
- **Perfect consistency (5/5)**: 0 (0.0%)
- **High consistency (4/5)**: 0 (0.0%)
- **Moderate consistency (3/5)**: 0 (0.0%)
- **API errors**: 0
- **Parse errors**: 0

**Sample disagreements**:

1. Case 32db7dc1-574d-461f-8d64-cfa8b6a5f919: 5 unique responses
   - 1x: `validation analysis:
- name/type alignment: the description names the instrument sumer (solar ultrav`
   - 1x: `validation analysis:
- name/type alignment: the description explicitly names the sumer instrument, a`
   - 1x: `validation analysis:
- name/type alignment: the described instrument is sumer and the proposed instr`
   - 1x: `validation analysis:
- name/type alignment: the proposed instrument is “solar ultraviolet measuremen`
   - 1x: `validation analysis:
- name/type alignment: the description names the instrument sumer (solar ultrav`
2. Case 8303268e-a8c3-4188-81b2-2f9d80e175bf: 5 unique responses
   - 1x: `validation analysis:
- name/type alignment: the description refers to “canopus and greenland magneto`
   - 1x: `validation analysis:
- name/type alignment: the description refers to magnetometer networks (canopus`
   - 1x: `validation analysis:
- name/type alignment: the description refers to magnetometer networks (canopus`
   - 1x: `validation analysis:
- name/type alignment: both the described networks and the proposed instrument `
   - 1x: `validation analysis:
- name/type alignment: both the original description and the proposed match ref`
3. Case d7769122-bee1-4216-b44a-7e8f0b35ee9f: 5 unique responses
   - 1x: `validation analysis:
- name/type alignment: the original description names “large angle spectrometri`
   - 1x: `validation analysis:
- name/type alignment: the description names “large angle spectrometric coronag`
   - 1x: `validation analysis:
- name/type alignment: the description names “large angle spectrometric coronag`
   - 1x: `validation analysis:
- name/type alignment: the description specifies “large angle spectrometric cor`
   - 1x: `validation analysis:
- name/type alignment: the description names “large angle spectrometric coronag`

### Mission Identification

- **Valid cases**: 100
- **Perfect consistency (5/5)**: 72 (72.0%)
- **High consistency (4/5)**: 17 (17.0%)
- **Moderate consistency (3/5)**: 3 (3.0%)
- **API errors**: 0
- **Parse errors**: 0

**Sample disagreements**:

1. Case 50d68f66-d56e-4352-8513-9b5ccbeba350: 2 unique responses
   - 4x: `311,312`
   - 1x: `312,311`
2. Case 9f6d29f0-7b20-401c-a9e3-9395112e500d: 2 unique responses
   - 4x: `307`
   - 1x: `307,1,360,311,312,350,138,139,123,126`
3. Case 7ff54450-2ed7-488b-92a2-bde83459391e: 3 unique responses
   - 2x: `11`
   - 2x: `11,9,10`
   - 1x: `9,10,11`

### Mission Selection

- **Valid cases**: 100
- **Perfect consistency (5/5)**: 81 (81.0%)
- **High consistency (4/5)**: 10 (10.0%)
- **Moderate consistency (3/5)**: 5 (5.0%)
- **API errors**: 0
- **Parse errors**: 0

**Sample disagreements**:

1. Case e545b829-0e9e-4f9e-844b-0ccbffcd603c: 2 unique responses
   - 4x: `0`
   - 1x: `1`
2. Case e7e5af7e-7943-4596-a58c-7124d2ea0d63: 2 unique responses
   - 4x: `1`
   - 1x: `0`
3. Case 423f19d5-7051-4ba6-b791-0acc7b73cf68: 2 unique responses
   - 4x: `0`
   - 1x: `1`

### Physobs Normalization

- **Valid cases**: 99
- **Perfect consistency (5/5)**: 67 (67.7%)
- **High consistency (4/5)**: 17 (17.2%)
- **Moderate consistency (3/5)**: 13 (13.1%)
- **API errors**: 1
- **Parse errors**: 0

**Sample disagreements**:

1. Case b03f076a-0989-4cf4-8b09-ab8955c8bb93: 2 unique responses
   - 3x: `uncertain`
   - 2x: `intensity`
2. Case d996bfbc-3e9b-47f6-85e2-15362b0410c2: 2 unique responses
   - 4x: `uncertain`
   - 1x: `wave_power`
3. Case 80d6dcca-d36b-4181-ad63-b53ea2ba4dfd: 2 unique responses
   - 4x: `vector_magnetic_field`
   - 1x: `los_magnetic_field`

### Time Normalization

- **Valid cases**: 95
- **Perfect consistency (5/5)**: 82 (86.3%)
- **High consistency (4/5)**: 6 (6.3%)
- **Moderate consistency (3/5)**: 6 (6.3%)
- **API errors**: 5
- **Parse errors**: 0

**Sample disagreements**:

1. Case 6db4d880-039b-4b8d-9305-7701c9170bdd: 2 unique responses
   - 4x: `{"original_text": "2013-10-11 (four-day interval around the event, approx.)", "is_approximate": true`
   - 1x: `{"original_text": "2013-10-11 (four-day interval around the event, approx.)", "is_approximate": true`
2. Case 496fb041-96c1-49e3-9dd7-080acf8fbf17: 3 unique responses
   - 3x: `{"original_text": "2009-09-26 15:53:10.860 ut (\u223c340 ms time window)", "is_approximate": false, `
   - 1x: `{"original_text": "2009-09-26 15:53:10.860 ut (\u223c340 ms time window)", "is_approximate": false, `
   - 1x: `{"original_text": "2009-09-26 15:53:10.860 ut (\u223c340 ms time window)", "is_approximate": true, "`
3. Case 36db6bb4-8351-4556-8fae-9fc2fb7849ee: 2 unique responses
   - 3x: `{"original_text": "1999-10-24", "is_approximate": false, "start_datetime": "1999-10-24t00:00:00z", "`
   - 2x: `{"original_text": "1999-10-24", "is_approximate": false, "start_datetime": "1999-10-24t00:00:00z", "`

### Wavelength Normalization

- **Valid cases**: 100
- **Perfect consistency (5/5)**: 98 (98.0%)
- **High consistency (4/5)**: 0 (0.0%)
- **Moderate consistency (3/5)**: 0 (0.0%)
- **API errors**: 0
- **Parse errors**: 0

**Sample disagreements**:

1. Case 5397f1fd-0928-4f8f-82d8-6a50c8011d43: 4 unique responses
   - 2x: `83-2220 kev, 83-2000 kev`
   - 1x: `83-2220 kev`
   - 1x: `83 kev, 2.22 mev, 2 mev`
   - 1x: `83-2000 kev, 83-2220 kev`
2. Case 82838cd0-9bfc-443d-bbef-b6a2007c8c9f: 3 unique responses
   - 2x: `83-2220 kev, 83-2000 kev`
   - 2x: `83-2220 kev`
   - 1x: `83 kev-2.22 mev, 83 kev-2 mev`
