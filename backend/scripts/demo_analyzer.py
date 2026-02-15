#!/usr/bin/env python3
"""Demo: Run DesignAnalyzerNode on real design_export.json and show results."""

import asyncio
import json
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from workflow.nodes.design import DesignAnalyzerNode


async def main():
    json_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "data", "design_export", "design_export.json"
    )
    json_path = os.path.abspath(json_path)

    print(f"=== DesignAnalyzerNode Demo ===")
    print(f"Input: {json_path}\n")

    node = DesignAnalyzerNode(
        node_id="demo_analyzer",
        node_type="design_analyzer",
        config={"design_source": "json", "design_file": json_path},
    )

    result = await node.execute({})

    # --- Component breakdown ---
    print(f"Total components: {result['total_components']}")
    print(f"\n{'='*60}")
    print("COMPONENT LIST (implementation order):")
    print(f"{'='*60}")

    for i, comp in enumerate(result["components"]):
        print(f"\n[{i+1}] {comp['name']}")
        print(f"    Type:     {comp['type']}")
        print(f"    Node ID:  {comp['node_id']}")
        print(f"    Bounds:   {comp['bounds']['width']}x{comp['bounds']['height']} @ ({comp['bounds']['x']}, {comp['bounds']['y']})")
        print(f"    Children: {comp['children_count']} — {comp.get('children_names', [])}")
        print(f"    Neighbors: {comp['neighbors']}")
        print(f"    Text:     {comp.get('text_content', [])}")
        print(f"    Notes:    {comp.get('notes', '')}")
        print(f"    Screenshot: {comp.get('screenshot_path', 'none')}")

    # --- Design tokens ---
    tokens = result["tokens"]
    print(f"\n{'='*60}")
    print("DESIGN TOKENS:")
    print(f"{'='*60}")
    for category, values in tokens.items():
        if values:
            print(f"\n  {category}:")
            if isinstance(values, dict):
                for k, v in values.items():
                    print(f"    --{k}: {v}")
            else:
                print(f"    {values}")

    # --- Skeleton structure ---
    skeleton = result["skeleton_structure"]
    print(f"\n{'='*60}")
    print("SKELETON STRUCTURE:")
    print(f"{'='*60}")
    print(f"  Layout: {skeleton['layout']}")
    print(f"  Size:   {skeleton['width']}x{skeleton['height']}")
    print(f"  Sections:")
    for s in skeleton.get("sections", []):
        b = s.get("bounds", {})
        print(f"    - {s['name']} ({s['type']}) {b.get('width', 0)}x{b.get('height', 0)}")

    # --- Registry state ---
    reg = result["component_registry"]
    print(f"\n{'='*60}")
    print("COMPONENT REGISTRY (initialized):")
    print(f"{'='*60}")
    print(f"  Components: {reg['total']} (completed: {reg['completed']}, failed: {reg['failed']})")
    print(f"  Tokens:     {len(reg['tokens'])} categories")
    print(f"  Skeleton:   {'set' if reg['skeleton_code'] else 'empty (will be generated next)'}")
    print(f"\n  current_component_index: {result['current_component_index']}")
    print(f"\n=== Pipeline would now proceed to: SkeletonGenerator → ComponentLoop({result['total_components']}x) → Assembler ===")


if __name__ == "__main__":
    asyncio.run(main())
