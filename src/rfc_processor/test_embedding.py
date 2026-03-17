import os
import json
import numpy as np
from global_recursor import RFCGraphOrchestrator

# 1. 先把图构建出来
orchestrator = RFCGraphOrchestrator(
    max_depth=1,
    save_dir="../../RFCs/",
    enable_embeddings=True
)
graph = orchestrator.fetch_and_build("RFC7858")

# 2. 检查向量文件
npy_path = "../../RFCs/vector_store/section_embeddings.npy"
index_path = "../../RFCs/vector_store/section_embedding_index.json"

print("=== File Check ===")
print("npy exists:", os.path.exists(npy_path))
print("index exists:", os.path.exists(index_path))

matrix = np.load(npy_path)
with open(index_path, "r", encoding="utf-8") as f:
    id_to_row = json.load(f)

print("\n=== Shape Check ===")
print("matrix shape:", matrix.shape)
print("num ids:", len(id_to_row))
print("dtype:", matrix.dtype)

# 3. 检查图中的 embedding_id
print("\n=== Graph Check ===")
section_count = 0
missing_embedding_id = []
missing_in_index = []

for node_id, data in graph.nodes(data=True):
    if data.get("node_type") != "Section":
        continue

    section_count += 1
    emb_id = data.get("embedding_id")

    if not emb_id:
        missing_embedding_id.append(node_id)
        continue

    if emb_id not in id_to_row:
        missing_in_index.append((node_id, emb_id))

print("section_count:", section_count)
print("missing embedding_id:", len(missing_embedding_id))
print("missing in index:", len(missing_in_index))

# 4. 检查归一化
print("\n=== Normalization Check ===")
norms = np.linalg.norm(matrix, axis=1)
print("norm min:", float(norms.min()))
print("norm max:", float(norms.max()))
print("norm mean:", float(norms.mean()))
print("bad rows:", int(np.sum(np.abs(norms - 1.0) > 1e-3)))
