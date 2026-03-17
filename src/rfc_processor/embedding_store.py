import json
from typing import Optional
import numpy as np


class NumpyEmbeddingStore:
    def __init__(self, npy_path: str, index_path: str):
        self.matrix = np.load(npy_path)
        with open(index_path, "r", encoding="utf-8") as f:
            self.id_to_row = json.load(f)

        if self.matrix.dtype != np.float32:
            self.matrix = self.matrix.astype(np.float32)

    def get(self, embedding_id: str) -> Optional[np.ndarray]:
        row = self.id_to_row.get(embedding_id)
        if row is None:
            return None
        return self.matrix[row]

    def get_many(self, embedding_ids: list[str]):
        valid_ids = []
        rows = []

        for emb_id in embedding_ids:
            row = self.id_to_row.get(emb_id)
            if row is None:
                continue
            valid_ids.append(emb_id)
            rows.append(row)

        if not rows:
            dim = self.matrix.shape[1]
            return [], np.empty((0, dim), dtype=np.float32)

        return valid_ids, self.matrix[rows]