from mem0 import Memory
from pathlib import Path
import os


def init_mem0(bank_id: str = "default") -> Memory:
    vector_db_base = os.getenv("MEM0_VECTOR_DB_PATH", "./chroma_db")
    history_db_base = os.getenv("MEM0_HISTORY_DB_PATH", "./mem0_history")
    ollama_api = os.getenv("OLLAMA_API", "http://localhost:11434")

    # Mem0's Ollama providers may read OLLAMA_HOST internally, so align it
    # with the runtime API setting to avoid connection mismatches.
    if not os.getenv("OLLAMA_HOST"):
        os.environ["OLLAMA_HOST"] = ollama_api

    vector_db_path = os.path.join(vector_db_base, bank_id)
    history_db_path = os.path.join(history_db_base, bank_id, f"{bank_id}.db")

    Path(vector_db_path).mkdir(parents=True, exist_ok=True)
    Path(history_db_path).parent.mkdir(parents=True, exist_ok=True)

    memory = Memory.from_config({
        "llm": {
            "provider": "ollama",
            "config": {
                "model": "phi4-mini",
                "ollama_base_url": ollama_api,
                "temperature": 0.7,
                "top_p": 0.9
            }
        },
        "embedder": {
            "provider": "ollama",
            "config": {
                "model": "nomic-embed-text",
                "ollama_base_url": ollama_api
            }
        },
        "vector_store": {
            "provider": "chroma",
            "config": {
                "collection_name": f"ps01_{bank_id}",
                "path": vector_db_path
            }
        },
        "history_db_path": history_db_path
    })
    return memory
