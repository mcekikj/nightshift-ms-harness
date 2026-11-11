#!/usr/bin/env python
"""Create (or inspect) the Foundry Memory store the experiment uses, and clean up scopes afterwards.

With the Night Shift repository's virtual environment (see README.md, Layout):

    python setup_memory_store.py                      # create if missing, then show it
    python setup_memory_store.py --chat-model gpt-6-luna --embedding-model text-embedding-3-small
    python setup_memory_store.py --delete-scope nightshift-20261111-000619-run1

The project endpoint comes from FOUNDRY_PROJECT_ENDPOINT in the Night Shift .env. The store needs a chat and an embedding
deployment on the Foundry account, and the project's system-assigned identity needs the "Foundry User" role on that
account (see README.md).
"""

from __future__ import annotations

import argparse
import os
import sys

from config import MEMORY_STORE, NS_ROOT
from dotenv import load_dotenv


def main(args: argparse.Namespace) -> int:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import MemoryStoreDefaultDefinition, MemoryStoreDefaultOptions
    from azure.identity import AzureCliCredential

    load_dotenv(NS_ROOT / ".env")
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        print("Set FOUNDRY_PROJECT_ENDPOINT (see the Night Shift .env.example).", file=sys.stderr)
        return 2

    with AzureCliCredential() as credential, AIProjectClient(endpoint=endpoint, credential=credential, allow_preview=True) as client:
        stores = client.beta.memory_stores
        if args.delete_scope:
            result = stores.delete_scope(name=args.name, scope=args.delete_scope)
            print(f"deleted scope {args.delete_scope!r}: {result.as_dict() if hasattr(result, 'as_dict') else result}")
            return 0

        if args.name in {s.name for s in stores.list()}:
            store = stores.get(args.name)
            print(f"memory store {args.name!r} already exists")
        else:
            store = stores.create(
                name=args.name,
                description="Night Shift experiment: platform-extracted memory vs the agent's own notebook",
                definition=MemoryStoreDefaultDefinition(
                    chat_model=args.chat_model,
                    embedding_model=args.embedding_model,
                    options=MemoryStoreDefaultOptions(
                        user_profile_enabled=True, chat_summary_enabled=True, procedural_memory_enabled=True
                    ),
                ),
            )
            print(f"created memory store {args.name!r}")
        print(f"id: {store.id}")
        print(f"definition: {store.definition.as_dict() if hasattr(store.definition, 'as_dict') else store.definition}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", default=MEMORY_STORE, help="memory store name (the experiment runner uses the same constant)")
    p.add_argument("--chat-model", default=os.environ.get("FOUNDRY_MODEL", "gpt-6-luna"), help="chat deployment used for extraction")
    p.add_argument("--embedding-model", default="text-embedding-3-small", help="embedding deployment used for search")
    p.add_argument("--delete-scope", default=None, help="delete every memory in this scope and exit")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main(parse_args()))
