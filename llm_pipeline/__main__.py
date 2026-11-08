"""Command-line demo.

    python -m llm_pipeline examples/password_reset.json
    python -m llm_pipeline --text "Users must be able to reset their password via email."
    python -m llm_pipeline examples/password_reset.json --show-prompt
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .ambiguity import detect_ambiguities
from .coverage import Context
from .errors import PipelineError
from .pipeline import GenerationPipeline
from .prompts import prompt_debug_dump
from .schemas import RequirementInput
from .validation import validate_requirement


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m llm_pipeline", description="Generate tests from a requirement.")
    p.add_argument("file", nargs="?", help="JSON file containing a RequirementInput")
    p.add_argument("--text", help="Plain requirement text instead of a file")
    p.add_argument("--show-prompt", action="store_true", help="Print the prompt instead of calling the model")
    p.add_argument("-o", "--output", help="Write result JSON to this file")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.text:
        req = RequirementInput(description=args.text)
    elif args.file:
        with open(args.file, encoding="utf-8") as fh:
            req = RequirementInput.model_validate(json.load(fh))
    else:
        p.error("provide a JSON file or --text")

    try:
        if args.show_prompt:
            v = validate_requirement(req)
            print(prompt_debug_dump(v, detect_ambiguities(v), Context.from_requirement(v)))
            return 0
        result = asyncio.run(GenerationPipeline().generate(req))
    except PipelineError as exc:
        print(json.dumps({"error": exc.code, "message": exc.message, "details": exc.details}, indent=2),
              file=sys.stderr)
        return 1

    text = result.model_dump_json(indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Saved to {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
