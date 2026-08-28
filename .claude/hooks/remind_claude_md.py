import json
import sys


def main():
    data = json.load(sys.stdin)
    file_path = (
        data.get("tool_input", {}).get("file_path")
        or data.get("tool_response", {}).get("filePath")
        or ""
    )
    if not file_path or file_path.replace("\\", "/").endswith("CLAUDE.md"):
        return
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"Reminder: {file_path} was just changed. If this affects "
                "commands, architecture, or file structure described in "
                "CLAUDE.md, update CLAUDE.md to match."
            ),
        }
    }))


if __name__ == "__main__":
    main()
