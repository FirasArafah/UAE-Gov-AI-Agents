import argparse
import asyncio
from pathlib import Path

from synora.db.session import AsyncSessionLocal
from synora.scenarios.loader import load_scenario_from_file


async def seed(force: bool = False) -> None:
    scenarios_dir = Path("/app/data/scenarios")
    if not scenarios_dir.exists():
        print(f"Directory not found: {scenarios_dir}")
        return

    files = sorted(scenarios_dir.glob("*.json"))
    if not files:
        print(f"No scenario JSON files in {scenarios_dir}")
        return

    async with AsyncSessionLocal() as db:
        for path in files:
            scenario = await load_scenario_from_file(db, path, force=force)
            print(f"OK  {path.name} -> scenario '{scenario.slug}' (id={scenario.id})")

    print(f"\nLoaded {len(files)} scenario(s).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load scenario JSON files into the database.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Update scenarios that already exist and replace their events.",
    )
    args = parser.parse_args()
    asyncio.run(seed(force=args.force))


if __name__ == "__main__":
    main()
