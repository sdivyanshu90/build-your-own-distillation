# Examples

Runnable configurations and request bodies for Distillery.

## Config files (`configs/`) — for the CLI

These run a full distillation **locally** with the `distillery distill` command (no DB/queue needed).
The `response_based` and `feature_based` examples use the **offline tiny-model path**
(`config_only: true`) and inline data, so they complete in seconds on CPU with no downloads:

```bash
distillery distill examples/configs/response_based.json --output ./artifacts/demo-response
distillery distill examples/configs/feature_based.json  --output ./artifacts/demo-feature
```

The `llm_teacher` example calls a hosted LLM to synthesise data, so it needs a key:

```bash
export DISTILLERY_LLM__ANTHROPIC_API_KEY=sk-ant-...
distillery distill examples/configs/llm_teacher.json --output ./artifacts/demo-llm
```

### Using real models

Swap the `config_only` tiny models for real HuggingFace models and a real dataset, e.g.:

```json
"teacher": {"name_or_path": "textattack/bert-base-uncased-SST-2", "num_labels": 2, "max_seq_length": 128},
"student": {"name_or_path": "distilbert-base-uncased", "num_labels": 2, "max_seq_length": 128},
"dataset": {"format": "hf_hub", "reference": "glue/sst2", "text_column": "sentence",
            "label_column": "label", "eval_split": "validation", "max_train_samples": 5000}
```

Remember the **shared-tokenizer constraint** for response/feature strategies: teacher and student
must share a tokenizer/vocabulary and have equal `num_labels`.

## Request bodies (`requests/`) — for the REST API

Wrapped as `{ "name", "config" }` for `POST /api/v1/jobs`:

```bash
KEY=dev-local-admin-key
curl -s -X POST http://localhost:8000/api/v1/jobs \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d @examples/requests/create_job_response_based.json | jq .
```

## Python SDK snippet

`sdk_example.py` creates a job, polls it, and prints the evaluation + artifacts:

```bash
pip install httpx
export DISTILLERY_BASE_URL=http://localhost:8000
export DISTILLERY_API_KEY=dev-local-admin-key
python examples/sdk_example.py
```
