# Selected embedding model for semantic-quality evaluation

- Provider: `qdrant_cloud_inference`
- Model: `sentence-transformers/all-minilm-l6-v2`
- Dense vector dimension: **384**
- MINE-TRACE distance metric: **cosine**
- Qdrant documentation checked: **2026-10-03**
- Source: https://qdrant.tech/documentation/cloud/inference/

Qdrant's current Cloud Inference documentation lists `sentence-transformers/all-minilm-l6-v2` as a Qdrant-hosted dense text model with 384 dimensions. The benchmark validates that the configured provider/model match `selected_embedding_model.json` before executing.

The benchmark does **not** translate Qdrant similarity scores into confidence, factual probability, probability of root cause, or proof of equivalence.
