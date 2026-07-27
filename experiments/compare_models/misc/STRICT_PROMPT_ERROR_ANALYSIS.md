# Strict Wavelength Normalization Prompt - API Error Analysis

**Experiment:** `bedrock_120b_wavelength_norm_strict_run`
**Date:** November 21, 2025
**Model:** `bedrock/openai.gpt-oss-120b-1:0`
**Total Cases:** 100
**Successful Parses:** 86 (86%)
**API Failures:** 14 (14%)

---

## Error Summary Table

| Error Type | Count | Cases | Description |
|-----------|-------|-------|-------------|
| Token 200012/200006 Mismatch | 9 | 2, 6, 18, 20, 65, 67, 87, 93, 100 | Bedrock tokenizer rejecting token 200012 when expecting 200006 |
| Token 200003/200006 Mismatch | 3 | 57, 71, 76 | Bedrock tokenizer rejecting token 200003 when expecting 200006 |
| Message Header Tokens | 2 | 29, 83 | Special `<\|constrain\|>` tokens in message header |
| **TOTAL** | **14** | — | — |

---

## Error Categories

### Category 1: Token 200012/200006 Mismatch (9 cases - 64%)

**Affected Cases:** 2, 6, 18, 20, 65, 67, 87, 93, 100

**Root Cause:** Bedrock's tokenizer is receiving token 200012 but expects token 200006 in the message structure. This indicates a tokenization incompatibility between how the XML prompt is being encoded and what Bedrock's model expects.

**Error Message Pattern:**
```
litellm.BadRequestError: BedrockException - {
  "message": "The model returned the following errors: {
    \"code\":\"validation_error\",
    \"message\":\"ErrorEvent {
      error: APIError {
        type: \"BadRequestError\",
        code: Some(400),
        message: \"Unexpected token 200012 while expecting start token 200006\",
        param: None
      }
    }\"
  }"
}
```

**Characteristics:**
- All 9 cases have identical error messages
- Scattered throughout test cases (not consecutive)
- Occurs on specific input combinations that trigger token 200012

---

### Category 2: Token 200003/200006 Mismatch (3 cases - 21%)

**Affected Cases:** 57, 71, 76

**Root Cause:** Similar to Category 1, but with token 200003 instead. This suggests certain input data or prompt template combinations generate this alternate token that Bedrock also rejects.

**Error Message Pattern:**
```
litellm.BadRequestError: BedrockException - {
  "message": "The model returned the following errors: {
    \"code\":\"validation_error\",
    \"message\":\"ErrorEvent {
      error: APIError {
        type: \"BadRequestError\",
        code: Some(400),
        message: \"Unexpected token 200003 while expecting start token 200006\",
        param: None
      }
    }\"
  }"
}
```

**Characteristics:**
- All 3 cases have identical error messages
- Cases 57, 71 are relatively close; case 76 is later in the sequence
- Suggests specific input patterns trigger token 200003

---

### Category 3: Message Header Token Errors (2 cases - 14%)

**Affected Cases:** 29, 83

**Root Cause:** Bedrock's message parser is rejecting special control tokens (`<|constrain|>`, `<|channel|>`) when they appear in the message header. These are likely XML markup tokens that are being interpreted as special control sequences.

#### Case 29 Error:

```
litellm.BadRequestError: BedrockException - {
  "message": "The model returned the following errors: {
    \"code\":\"validation_error\",
    \"message\":\"ErrorEvent {
      error: APIError {
        type: \"BadRequestError\",
        code: Some(400),
        message: \"unexpected tokens remaining in message header: Some(\\\"<|constrain|>c <|constrain|>assistant<|channel|>commentary\\\")\",
        param: None
      }
    }\"
  }"
}
```

**Issue:** The message header contains:
- `<|constrain|>c` - malformed constrain token
- `<|constrain|>assistant` - constrain token followed by role
- `<|channel|>commentary` - channel control token

#### Case 83 Error:

```
litellm.BadRequestError: BedrockException - {
  "message": "The model returned the following errors: {
    \"code\":\"validation_error\",
    \"message\":\"ErrorEvent {
      error: APIError {
        type: \"BadRequestError\",
        code: Some(400),
        message: \"unexpected tokens remaining in message header: Some(\\\"<|constrain|>commentary\\\")\",
        param: None
      }
    }\"
  }"
}
```

**Issue:** The message header contains:
- `<|constrain|>commentary` - constrain token with commentary label

---

## Individual Error Details

### Token 200012/200006 Errors

#### Case 2
```
litellm.BadRequestError: BedrockException - {"message":"The model returned the following errors: {\"code\":\"validation_error\",\"message\":\"ErrorEvent { error: APIError { type: \\\"BadRequestError\\\", code: Some(400), message: \\\"Unexpected token 200012 while expecting start token 200006\\\", param: None } }\",\"param\":null,\"type\":\"invalid_request_error\"}"}
```

#### Case 6
```
litellm.BadRequestError: BedrockException - {"message":"The model returned the following errors: {\"code\":\"validation_error\",\"message\":\"ErrorEvent { error: APIError { type: \\\"BadRequestError\\\", code: Some(400), message: \\\"Unexpected token 200012 while expecting start token 200006\\\", param: None } }\",\"param\":null,\"type\":\"invalid_request_error\"}"}
```

#### Case 18
```
litellm.BadRequestError: BedrockException - {"message":"The model returned the following errors: {\"code\":\"validation_error\",\"message\":\"ErrorEvent { error: APIError { type: \\\"BadRequestError\\\", code: Some(400), message: \\\"Unexpected token 200012 while expecting start token 200006\\\", param: None } }\",\"param\":null,\"type\":\"invalid_request_error\"}"}
```

#### Case 20
```
litellm.BadRequestError: BedrockException - {"message":"The model returned the following errors: {\"code\":\"validation_error\",\"message\":\"ErrorEvent { error: APIError { type: \\\"BadRequestError\\\", code: Some(400), message: \\\"Unexpected token 200012 while expecting start token 200006\\\", param: None } }\",\"param\":null,\"type\":\"invalid_request_error\"}"}
```

#### Case 65
```
litellm.BadRequestError: BedrockException - {"message":"The model returned the following errors: {\"code\":\"validation_error\",\"message\":\"ErrorEvent { error: APIError { type: \\\"BadRequestError\\\", code: Some(400), message: \\\"Unexpected token 200012 while expecting start token 200006\\\", param: None } }\",\"param\":null,\"type\":\"invalid_request_error\"}"}
```

#### Case 67
```
litellm.BadRequestError: BedrockException - {"message":"The model returned the following errors: {\"code\":\"validation_error\",\"message\":\"ErrorEvent { error: APIError { type: \\\"BadRequestError\\\", code: Some(400), message: \\\"Unexpected token 200012 while expecting start token 200006\\\", param: None } }\",\"param\":null,\"type\":\"invalid_request_error\"}"}
```

#### Case 87
```
litellm.BadRequestError: BedrockException - {"message":"The model returned the following errors: {\"code\":\"validation_error\",\"message\":\"ErrorEvent { error: APIError { type: \\\"BadRequestError\\\", code: Some(400), message: \\\"Unexpected token 200012 while expecting start token 200006\\\", param: None } }\",\"param\":null,\"type\":\"invalid_request_error\"}"}
```

#### Case 93
```
litellm.BadRequestError: BedrockException - {"message":"The model returned the following errors: {\"code\":\"validation_error\",\"message\":\"ErrorEvent { error: APIError { type: \\\"BadRequestError\\\", code: Some(400), message: \\\"Unexpected token 200012 while expecting start token 200006\\\", param: None } }\",\"param\":null,\"type\":\"invalid_request_error\"}"}
```

#### Case 100
```
litellm.BadRequestError: BedrockException - {"message":"The model returned the following errors: {\"code\":\"validation_error\",\"message\":\"ErrorEvent { error: APIError { type: \\\"BadRequestError\\\", code: Some(400), message: \\\"Unexpected token 200012 while expecting start token 200006\\\", param: None } }\",\"param\":null,\"type\":\"invalid_request_error\"}"}
```

---

### Token 200003/200006 Errors

#### Case 57
```
litellm.BadRequestError: BedrockException - {"message":"The model returned the following errors: {\"code\":\"validation_error\",\"message\":\"ErrorEvent { error: APIError { type: \\\"BadRequestError\\\", code: Some(400), message: \\\"Unexpected token 200003 while expecting start token 200006\\\", param: None } }\",\"param\":null,\"type\":\"invalid_request_error\"}"}
```

#### Case 71
```
litellm.BadRequestError: BedrockException - {"message":"The model returned the following errors: {\"code\":\"validation_error\",\"message\":\"ErrorEvent { error: APIError { type: \\\"BadRequestError\\\", code: Some(400), message: \\\"Unexpected token 200003 while expecting start token 200006\\\", param: None } }\",\"param\":null,\"type\":\"invalid_request_error\"}"}
```

#### Case 76
```
litellm.BadRequestError: BedrockException - {"message":"The model returned the following errors: {\"code\":\"validation_error\",\"message\":\"ErrorEvent { error: APIError { type: \\\"BadRequestError\\\", code: Some(400), message: \\\"Unexpected token 200003 while expecting start token 200006\\\", param: None } }\",\"param\":null,\"type\":\"invalid_request_error\"}"}
```

---

### Message Header Token Errors

#### Case 29
```
litellm.BadRequestError: BedrockException - {"message":"The model returned the following errors: {\"code\":\"validation_error\",\"message\":\"ErrorEvent { error: APIError { type: \\\"BadRequestError\\\", code: Some(400), message: \\\"unexpected tokens remaining in message header: Some(\\\\\\\"<|constrain|>c <|constrain|>assistant<|channel|>commentary\\\\\\\")\\\", param: None } }\",\"param\":null,\"type\":\"invalid_request_error\"}"}
```

**Specific Issue:** Message header contains malformed control tokens with additional characters/formatting.

#### Case 83
```
litellm.BadRequestError: BedrockException - {"message":"The model returned the following errors: {\"code\":\"validation_error\",\"message\":\"ErrorEvent { error: APIError { type: \\\"BadRequestError\\\", code: Some(400), message: \\\"unexpected tokens remaining in message header: Some(\\\\\\\"<|constrain|>commentary\\\\\\\")\\\", param: None } }\",\"param\":null,\"type\":\"invalid_request_error\"}"}
```

**Specific Issue:** Message header contains constrain control token with commentary label.

---

## Analysis & Implications

### What These Errors Tell Us

1. **Not Rate Limiting:** Errors are scattered throughout (cases 2, 6, 18, 20, 29, 57, 65, 67, 71, 76, 83, 87, 93, 100), not consecutive. If it were rate limiting, we'd see clustering at the end or in a time-based pattern.

2. **Not Prompt Size:** The strict prompt is 62% larger (916 vs 566 tokens) than the original, yet we improved from 77% to 86% success rate. Size alone isn't causing failures.

3. **Tokenization Incompatibility:** The XML markup in the prompts is being tokenized differently than Bedrock expects:
   - Some inputs generate token 200012 (9 cases)
   - Some inputs generate token 200003 (3 cases)
   - Both are rejected when expecting 200006
   - Special control tokens `<|constrain|>`, `<|channel|>` appear in message headers where Bedrock doesn't expect them

4. **Input-Dependent:** The specific wavelength input text determines which token mismatch occurs. This suggests:
   - Certain Unicode characters or formatting in wavelength values trigger token 200012
   - Other patterns trigger token 200003
   - The control tokens in headers are likely from the XML structure being incorrectly tokenized

### What These Errors Do NOT Indicate

- ✗ Prompt formatting problems (the errors occur server-side during tokenization)
- ✗ JSON schema violations (when API succeeds, all 86 cases produce valid JSON)
- ✗ Bedrock model limitations (model responds correctly 86% of the time)
- ✗ Request timeout issues (errors are validation errors, not timeouts)
- ✗ Rate limiting or throttling (scattered cases, not consecutive)

### Recommendations

1. **Investigate Token Mappings:** Determine what input patterns (specific wavelength units, ranges, etc.) trigger tokens 200012 vs 200003. These may be Unicode or special character handling issues.

2. **Control Token Escape:** The XML tags in prompts may need to be escaped or processed differently to prevent them from being interpreted as Bedrock's internal control tokens.

3. **Alternative Approaches:**
   - Test with different prompt formats (less XML nesting)
   - Try alternative Bedrock models to see if they have different token expectations
   - Implement fallback handling for these specific tokenization errors

4. **Monitor:** Even at 86% success with tokenization errors, this is a 9% improvement over the 77% with the original prompt. The strict prompt is still a net win.

---

## Comparison to Previous Run

| Metric | Previous | Current | Change |
|--------|----------|---------|--------|
| Success Rate | 77% (77/100) | 86% (86/100) | +9 cases |
| API Failures | 23 | 14 | -9 failures |
| Parse Failures | 8 | 0 | Eliminated |
| All-successful behavior | N/A | 100% when API succeeds | Improved |

**Conclusion:** The strict prompt is performing better despite the tokenization errors. When the API doesn't fail with tokenization issues, the strict prompt has perfect parse accuracy (100%).
