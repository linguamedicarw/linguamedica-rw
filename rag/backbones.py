"""
Component 5: the backbone, a frozen model (thesis 4.4.1, 4.4.3).

Decoding is greedy, with a fixed seed wherever the runtime uses one and a maximum output
length, and describe() names the exact checkpoint, so that the run log carries what is
needed to regenerate an output. After each call, `last` holds what the runtime reported:
the prompt and output lengths in tokens and why generation stopped ("length" means the
output was cut at the maximum and the item needs review).

    none          no model. The run measures the English side (matches, misses, term
                  recall) and writes the prompts: the miss rate before any model runs.
    echo          returns the English sentence unchanged. For testing the plumbing only.
    ollama        a model served by Ollama on this computer (the 4B model, for building).
    transformers  a Hugging Face checkpoint (Gemma 3 27B on Hellbender). TranslateGemma
                  takes --prompt-format gemma-raw: its own chat template accepts only a text
                  and two language codes, so a prompt with dictionary entries has to be sent
                  with Gemma's turn markers directly, as its model card describes for custom
                  prompts.

Nothing here trains, fine-tunes or updates a model.
"""

import json
import os
import platform
import urllib.request
from dataclasses import asdict, dataclass

BACKBONES = ("none", "echo", "ollama", "transformers")
PROMPT_FORMATS = ("chat", "gemma-raw")


@dataclass(frozen=True)
class Decoding:
    max_new_tokens: int = 256
    seed: int = 20261021
    strategy: str = "greedy"
    context_tokens: int = 8192      # Ollama's num_ctx; Ollama cuts a longer prompt from the start


def gemma_raw(prompt):
    """One user turn in Gemma's control tokens; the tokenizer adds <bos>."""
    return f"<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\n"


def sentence_of(prompt):
    """The English sentence at the end of a prompt (prompt.SENTENCE_HEAD and after)."""
    head = "English sentence:\n"
    return prompt.rsplit(head, 1)[-1].strip() if head in prompt else prompt.strip()


class Backbone:
    name = "?"
    prompt_format = "chat"

    def __init__(self, decoding=Decoding()):
        self.decoding = decoding
        self.last = {}

    def generate(self, prompt):
        raise NotImplementedError

    def describe(self):
        return {"backbone": self.name, "prompt_format": self.prompt_format,
                "decoding": asdict(self.decoding)}


class EchoBackbone(Backbone):
    """Returns the English sentence as given: checks the pipeline, translates nothing."""
    name = "echo"

    def generate(self, prompt):
        self.last = {"done_reason": "stop"}
        return sentence_of(prompt)

    def describe(self):
        return dict(super().describe(), checkpoint="echo (no model)")


class OllamaBackbone(Backbone):
    """A model served by a local Ollama (http://127.0.0.1:11434 unless OLLAMA_HOST says otherwise)."""
    name = "ollama"

    def __init__(self, model, decoding=Decoding(), host=None, opener=None):
        super().__init__(decoding)
        self.model = model if ":" in model else f"{model}:latest"
        host = host or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
        self.host = (host if host.startswith("http") else "http://" + host).rstrip("/")
        self.opener = opener or urllib.request.urlopen

    def _call(self, path, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.host + path, data=data,
                                         headers={"Content-Type": "application/json"})
        try:
            with self.opener(request, timeout=600) as response:
                return json.loads(response.read().decode("utf-8"))
        except OSError as exc:
            raise SystemExit(f"Could not reach Ollama at {self.host} ({exc}). Is it running, "
                             f"and is the model pulled (ollama pull {self.model})?") from None

    def request_body(self, prompt):
        return {"model": self.model, "prompt": prompt, "stream": False,
                "options": {"temperature": 0, "top_k": 1, "seed": self.decoding.seed,
                            "num_predict": self.decoding.max_new_tokens,
                            "num_ctx": self.decoding.context_tokens}}

    def generate(self, prompt):
        out = self._call("/api/generate", self.request_body(prompt))
        prompt_tokens = out.get("prompt_eval_count")
        self.last = {"done_reason": out.get("done_reason"), "prompt_tokens": prompt_tokens,
                     "output_tokens": out.get("eval_count")}
        if prompt_tokens is not None and prompt_tokens >= self.decoding.context_tokens:
            self.last["done_reason"] = "prompt_cut"
        return (out.get("response") or "").strip()

    def describe(self):
        """Names the checkpoint by its digest; stops the run if the model is not there."""
        tags = self._call("/api/tags").get("models", [])
        match = next((m for m in tags if self.model in (m.get("name"), m.get("model"))), None)
        if match is None or not match.get("digest"):
            raise SystemExit(f"Ollama has no model {self.model}; pull it first "
                             f"(ollama pull {self.model}).")
        return dict(super().describe(), model=self.model, host=self.host,
                    checkpoint=f"{match.get('name')}@{match['digest']}",
                    details=match.get("details"),
                    ollama_version=self._call("/api/version").get("version"))


class TransformersBackbone(Backbone):
    """A Hugging Face checkpoint, loaded once, greedy decoding."""
    name = "transformers"

    def __init__(self, model_id, decoding=Decoding(), prompt_format="chat", revision=None,
                 dtype="bfloat16", device_map="auto"):
        super().__init__(decoding)
        if prompt_format not in PROMPT_FORMATS:
            raise SystemExit(f"--prompt-format must be one of {', '.join(PROMPT_FORMATS)}")
        try:
            import torch
            import transformers
        except ImportError:
            raise SystemExit("The transformers backbone needs torch and transformers "
                             "(pip install torch transformers accelerate).") from None
        self.torch, self.transformers = torch, transformers
        self.model_id, self.revision, self.prompt_format, self.dtype = (
            model_id, revision, prompt_format, dtype)
        try:
            self.processor = transformers.AutoProcessor.from_pretrained(model_id, revision=revision)
        except (OSError, ValueError):
            self.processor = transformers.AutoTokenizer.from_pretrained(model_id, revision=revision)
        self.tokenizer = getattr(self.processor, "tokenizer", self.processor)
        self.is_processor = self.tokenizer is not self.processor
        classes = [getattr(transformers, n) for n in
                   ("AutoModelForImageTextToText", "AutoModelForCausalLM") if hasattr(transformers, n)]
        # transformers 4.56 renamed torch_dtype to dtype.
        major, minor = (int(x) for x in transformers.__version__.split(".")[:2])
        dtype_arg = {("dtype" if (major, minor) >= (4, 56) else "torch_dtype"): getattr(torch, dtype)}
        last = None
        for cls in classes:
            try:
                self.model = cls.from_pretrained(model_id, revision=revision,
                                                 device_map=device_map, **dtype_arg)
                break
            except (ValueError, KeyError) as exc:
                last = exc
        else:
            raise SystemExit(f"Could not load {model_id}: {last}")
        self.model.eval()

    def _inputs(self, prompt):
        if self.prompt_format == "gemma-raw":
            return self.tokenizer(gemma_raw(prompt), return_tensors="pt")
        content = [{"type": "text", "text": prompt}] if self.is_processor else prompt
        return self.processor.apply_chat_template(
            [{"role": "user", "content": content}], add_generation_prompt=True,
            tokenize=True, return_dict=True, return_tensors="pt")

    def generate(self, prompt):
        inputs = self._inputs(prompt).to(self.model.device)
        start = inputs["input_ids"].shape[-1]
        self.torch.manual_seed(self.decoding.seed)
        with self.torch.inference_mode():
            out = self.model.generate(**inputs, do_sample=False,
                                      max_new_tokens=self.decoding.max_new_tokens)
        new = out[0][start:]
        self.last = {"prompt_tokens": int(start), "output_tokens": int(len(new)),
                     "done_reason": "length" if len(new) >= self.decoding.max_new_tokens else "stop"}
        return self.tokenizer.decode(new, skip_special_tokens=True).strip()

    def describe(self):
        commit = getattr(self.model.config, "_commit_hash", None)
        info = dict(super().describe(), model=self.model_id, revision_requested=self.revision,
                    checkpoint=f"{self.model_id}@{commit}", dtype=self.dtype,
                    device=str(self.model.device), transformers=self.transformers.__version__,
                    torch=self.torch.__version__,
                    generation_config=self.model.generation_config.to_dict())
        if commit is None:
            info["checkpoint_note"] = ("no Hub commit known (a local folder?): name the "
                                       "checkpoint with --revision, or load it by its Hub id")
        return info


def make(name, model=None, decoding=Decoding(), prompt_format="chat", revision=None):
    """The backbone a run asked for; None for 'none'."""
    if name == "none":
        return None
    if name == "echo":
        return EchoBackbone(decoding)
    if not model:
        raise SystemExit(f"--backbone {name} needs --model (for example gemma3:4b with ollama, "
                         "google/gemma-3-27b-it with transformers).")
    if name == "ollama":
        if prompt_format != "chat":
            raise SystemExit("--prompt-format gemma-raw is for the transformers backbone; "
                             "Ollama applies the model's own chat template.")
        return OllamaBackbone(model, decoding)
    if name == "transformers":
        return TransformersBackbone(model, decoding, prompt_format, revision)
    raise SystemExit(f"--backbone must be one of {', '.join(BACKBONES)}")


def runtime():
    return {"python": platform.python_version(), "platform": platform.platform()}
