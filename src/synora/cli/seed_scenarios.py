import asyncio
from pathlib import Path

from synora.db.session import AsyncSessionLocal
from synora.scenarios.loader import load_scenario_from_file


async def seed() -> None:
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
            scenario = await load_scenario_from_file(db, path)
            print(f"OK  {path.name} -> scenario '{scenario.slug}' (id={scenario.id})")

    print(f"\nLoaded {len(files)} scenario(s).")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
