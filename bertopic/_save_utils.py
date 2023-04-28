import os
import sys
import json
import numpy as np

from pathlib import Path
from tempfile import TemporaryDirectory


# HuggingFace Hub
try:
    from huggingface_hub import (
        create_repo, get_hf_file_metadata,
        hf_hub_download, hf_hub_url,
        ModelCardData, repo_type_and_id_from_hf_id, upload_folder)
    _has_hf_hub = True
except ImportError:
    _has_hf_hub = False

# Typing
if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal
from typing import Union, Mapping, Any

# Pytorch check
try:
    import torch
    _has_torch = True
except ImportError:
    _has_torch = False

TOPICS_NAME = "topics.json"
CONFIG_NAME = "config.json"

HF_WEIGHTS_NAME = "topic_embeddings.bin"  # default pytorch pkl
HF_SAFE_WEIGHTS_NAME = "topic_embeddings.safetensors"  # safetensors version

CTFIDF_WEIGHTS_NAME = "ctfidf.bin"  # default pytorch pkl
CTFIDF_SAFE_WEIGHTS_NAME = "ctfidf.safetensors"  # safetensors version
CTFIDF_CFG_NAME = "ctfidf_config.json"

MODEL_CARD_TEMPLATE = """
---
tags:
- bertopic
library_name: bertopic
---

# {MODEL_NAME}

This is a [BERTopic](https://github.com/MaartenGr/BERTopic) model. 
BERTopic is a flexible and modular topic modeling framework that allows for the generation of easily interpretable topics from large datasets. 

## Usage 

To use this model, please install BERTopic:

```
pip install -U bertopic
```

You can use the model as follows:

```python
from bertopic import BERTopic
topic_model = BERTopic.load("{PATH}")

topic_model.get_topic_info()
```

## Topic overview

* Number of topics: {NR_TOPICS}
* Number of training documents: {NR_DOCUMENTS}

<details>
  <summary>Click here for an overview of all topics.</summary>
  
  {TOPICS}
  
</details>

## Training hyperparameters

{HYPERPARAMS}

## Framework versions

{FRAMEWORKS}
"""



def push_to_hf_hub(
        model,
        repo_id: str,
        commit_message: str = 'Add BERTopic model',
        token: str = None,
        revision: str = None,
        private: bool = False,
        create_pr: bool = False,
        model_card: bool = True,
        serialization: str = "safetensors",
        save_embedding_model: str = None,
        save_ctfidf: bool = False,
        ):
    """ Push your BERTopic model to a HuggingFace Hub

    Arguments:
        repo_id: The name of your HuggingFace repository
        commit_message: A commit message
        token: Token to add if not already logged in
        revision: Repository revision
        private: Whether to create a private repository
        create_pr: Whether to upload the model as a Pull Request
        model_card: Whether to automatically create a modelcard
        serialization: The type of serialization.
                       Either `safetensors` or `pytorch`
        save_embedding_model: A pointer towards a HuggingFace model to be loaded in with
                                SentenceTransformers. E.g.,
                                `sentence-transformers/all-MiniLM-L6-v2`
        save_ctfidf: Whether to save c-TF-IDF information
    """
    if not _has_hf_hub:
        raise ValueError("Make sure you have the huggingface hub installed via `pip install --upgrade huggingface_hub`")

    # Create repo if it doesn't exist yet and infer complete repo_id
    repo_url = create_repo(repo_id, token=token, private=private, exist_ok=True)
    _, repo_owner, repo_name = repo_type_and_id_from_hf_id(repo_url)
    repo_id = f"{repo_owner}/{repo_name}"

    # Temporarily save model and push to HF
    with TemporaryDirectory() as tmpdir:

        # Save model weights and config.
        model.save(tmpdir, serialization=serialization, save_embedding_model=save_embedding_model, save_ctfidf=save_ctfidf)

        # Add README if it does not exist
        try:
            get_hf_file_metadata(hf_hub_url(repo_id=repo_id, filename="README.md", revision=revision))
        except:
            if model_card:
                readme_text = generate_readme(model, repo_id)
                readme_path = Path(tmpdir) / "README.md"
                readme_path.write_text(readme_text, encoding='utf8')

        # Upload model
        return upload_folder(repo_id=repo_id, folder_path=tmpdir, revision=revision,
                             create_pr=create_pr, commit_message=commit_message)


def load_local_files(path):
    """ Load local BERTopic files """
    # Load json configs
    topics = load_cfg_from_json(path / TOPICS_NAME)
    params = load_cfg_from_json(path / CONFIG_NAME)

    # Load Topic Embeddings
    safetensor_path = path / HF_SAFE_WEIGHTS_NAME
    if safetensor_path.is_file():
        tensors = safetensors.torch.load_file(safetensor_path, device="cpu")
    else:
        torch_path = path / HF_WEIGHTS_NAME
        if torch_path.is_file():
            tensors = torch.load(torch_path, map_location="cpu")

    # c-TF-IDF
    ctfidf_tensors = None
    safetensor_path = path / CTFIDF_SAFE_WEIGHTS_NAME
    if safetensor_path.is_file():
        ctfidf_tensors = safetensors.torch.load_file(safetensor_path, device="cpu")
    else:
        torch_path = path / CTFIDF_WEIGHTS_NAME
        if torch_path.is_file():
            ctfidf_tensors = torch.load(torch_path, map_location="cpu")
    ctfidf_config = load_cfg_from_json(path / CTFIDF_CFG_NAME)

    return topics, params, tensors, ctfidf_tensors, ctfidf_config


def load_files_from_hf(path):
    """ Load files from HuggingFace. """
    path = str(path)

    # Configs
    topics = load_cfg_from_json(hf_hub_download(path, TOPICS_NAME, revision=None))
    params = load_cfg_from_json(hf_hub_download(path, CONFIG_NAME, revision=None))

    # Topic Embeddings
    try:
        tensors = hf_hub_download(path, HF_SAFE_WEIGHTS_NAME, revision=None)
        tensors = safetensors.torch.load_file(tensors, device="cpu")
    except:
        tensors = hf_hub_download(path, HF_WEIGHTS_NAME, revision=None)
        tensors = torch.load(tensors, map_location="cpu")

    # c-TF-IDF
    try:
        ctfidf_config = load_cfg_from_json(hf_hub_download(path, CTFIDF_CFG_NAME, revision=None))
        try:
            ctfidf_tensors = hf_hub_download(path, CTFIDF_SAFE_WEIGHTS_NAME, revision=None)
            ctfidf_tensors = safetensors.torch.load_file(ctfidf_tensors, device="cpu")
        except:
            ctfidf_tensors = hf_hub_download(path, CTFIDF_WEIGHTS_NAME, revision=None)
            ctfidf_tensors = torch.load(ctfidf_tensors, map_location="cpu")
    except:
        ctfidf_config, ctfidf_tensors = None, None

    return topics, params, tensors, ctfidf_tensors, ctfidf_config


def generate_readme(model, repo_id: str):
    """ Generate README for HuggingFace model card """
    model_card = MODEL_CARD_TEMPLATE
    topic_table_head = "| Topic ID | Topic Keywords | Topic Frequency | Label | \n|----------|----------------|-----------------|-------| \n"

    # Get Statistics
    model_name = repo_id.split("/")[-1]
    params = {param: value for param, value in model.get_params().items() if "model" not in param}
    params = "\n".join([f"* {param}: {value}" for param, value in params.items()])
    topics = sorted(list(set(model.topics_)))
    nr_topics = str(len(set(model.topics_)))
    nr_documents = str(model.c_tf_idf_.shape[1])

    # Topic information
    topic_keywords = [" - ".join(list(zip(*model.get_topic(topic)))[0][:5]) for topic in topics]
    topic_freq = [model.get_topic_freq(topic) for topic in topics]
    topic_labels = model.custom_labels_ if model.custom_labels_ else [model.topic_labels_[topic] for topic in topics]
    topics = [f"| {topic} | {topic_keywords[index]} | {topic_freq[topic]} | {topic_labels[index]} | \n" for index, topic in enumerate(topics)]
    topics = topic_table_head + "".join(topics)
    frameworks = "\n".join([f"* {param}: {value}" for param, value in get_package_versions().items()])

    # Fill Statistics into model card
    model_card = model_card.replace("{MODEL_NAME}", model_name)
    model_card = model_card.replace("{PATH}", repo_id)
    model_card = model_card.replace("{NR_TOPICS}",  nr_topics)
    model_card = model_card.replace("{TOPICS}",  topics.strip())
    model_card = model_card.replace("{NR_DOCUMENTS}", nr_documents)
    model_card = model_card.replace("{HYPERPARAMS}", params)
    model_card = model_card.replace("{FRAMEWORKS}", frameworks)
    
    return model_card


def save_hf(model, save_directory, serialization: str):
    """ Save topic embeddings, either safely (using safetensors) or using legacy pytorch """
    tensors = torch.from_numpy(np.array(model.topic_embeddings_, dtype=np.float32))
    tensors = {"topic_embeddings": tensors}

    if serialization == "safetensors":
        try:
            import safetensors
            safetensors.torch.save_file(tensors, save_directory / HF_SAFE_WEIGHTS_NAME)
        except ImportError:
            raise ValueError("`pip install safetensors` to use .safetensors")
        safetensors.torch.save_file(tensors, save_directory / HF_SAFE_WEIGHTS_NAME)
    if serialization == "pytorch":
        assert _has_torch, "`pip install pytorch` to save as bin"
        torch.save(tensors, save_directory / HF_WEIGHTS_NAME)


def save_ctfidf(model,
                save_directory: str,
                serialization: str):
    """ Save c-TF-IDF sparse matrix """
    indptr = torch.from_numpy(model.c_tf_idf_.indptr)
    indices = torch.from_numpy(model.c_tf_idf_.indices)
    data = torch.from_numpy(model.c_tf_idf_.data)
    shape = torch.from_numpy(np.array(model.c_tf_idf_.shape))
    diag = torch.from_numpy(np.array(model.ctfidf_model._idf_diag.data))
    tensors = {
        "indptr": indptr,
        "indices": indices,
        "data": data,
        "shape": shape,
        "diag": diag
    }

    if serialization == "safetensors":
        try:
            import safetensors
            safetensors.torch.save_file(tensors, save_directory / CTFIDF_SAFE_WEIGHTS_NAME)
        except ImportError:
            raise ValueError("`pip install safetensors` to use .safetensors")
    if serialization == "pytorch":
        assert _has_torch, "`pip install pytorch` to save as .bin"
        torch.save(tensors, save_directory / CTFIDF_WEIGHTS_NAME)


def save_ctfidf_config(model, path):
    """ Save parameters to recreate CountVectorizer and c-TF-IDF """
    config = {}

    # Recreate ClassTfidfTransformer
    config["ctfidf_model"] = {
        "bm25_weighting": model.ctfidf_model.bm25_weighting,
        "reduce_frequent_words": model.ctfidf_model.reduce_frequent_words
    }

    # Recreate CountVectorizer
    cv_params = model.vectorizer_model.get_params()
    del cv_params["tokenizer"], cv_params["preprocessor"], cv_params["dtype"]
    if not isinstance(cv_params["analyzer"], str):
        del cv_params["analyzer"]

    config["vectorizer_model"] = {
        "params": cv_params,
        "vocab": model.vectorizer_model.vocabulary_
    }

    with path.open('w') as f:
        json.dump(config, f, indent=2)


def save_config(model, path: str, embedding_model):
    """ Save BERTopic configuration """
    path = Path(path)
    params = model.get_params()
    config = {param: value for param, value in params.items() if "model" not in param}

    # Embedding model tag to be used in sentence-transformers
    if embedding_model:
        config["embedding_model"] = embedding_model

    with path.open('w') as f:
        json.dump(config, f, indent=2)

    return config


def save_topics(model, path: str):
    """ Save Topic-specific information """
    path = Path(path)
    topics = {
        "topic_representations": model.topic_representations_,
        "topics": [int(topic) for topic in model.topics_],
        "topic_sizes": model.topic_sizes_,
        "topic_mapper": np.array(model.topic_mapper_.mappings_, dtype=int).tolist(),
        "topic_labels": model.topic_labels_,
        "custom_labels": model.custom_labels_,
        "_outliers": int(model._outliers)
    }

    with path.open('w') as f:
        json.dump(topics, f, indent=2, cls=NumpyEncoder)


def load_cfg_from_json(json_file: Union[str, os.PathLike]):
    """ Load configuration from json """
    with open(json_file, "r", encoding="utf-8") as reader:
        text = reader.read()
    return json.loads(text)


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        return super(NumpyEncoder, self).default(obj)



def get_package_versions():
    """ Get versions of main dependencies of BERTopic """
    try:
        import platform
        from numpy import __version__ as np_version
        
        try:
            from importlib.metadata import version
            hdbscan_version = version('hdbscan')
        except:
            hdbscan_version = None

        from umap import __version__ as umap_version
        from pandas import __version__ as pandas_version
        from sklearn import __version__ as sklearn_version
        from sentence_transformers import __version__ as sbert_version
        from numba import __version__ as numba_version
        from transformers import __version__ as transformers_version
        
        from plotly import __version__ as plotly_version
        return {"Numpy": np_version, "HDBSCAN": hdbscan_version, "UMAP": umap_version, 
                "Pandas": pandas_version, "Scikit-Learn": sklearn_version, 
                "Sentence-transformers": sbert_version, "Transformers": transformers_version,
                "Numba": numba_version, "Plotly": plotly_version, "Python": platform.python_version()}
    except Exception as e:
        return e