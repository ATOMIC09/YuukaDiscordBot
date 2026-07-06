# Developer Documentation & Version Releases

This file contains internal technical details, installation guides, and command instructions for development. Keep these commands out of the main `README.md` to keep the public view clean and focused on features.

---

## 🛠️ Project Setup

This project uses [uv](https://astral.sh/uv) to manage Python packages and virtual environments.

### 1. Install Dependencies
To install the dependencies and create/update the virtual environment:
```bash
uv sync
```

### 2. Run the Bot
To launch the bot locally:
```bash
uv run main.py
```

---

## 🚀 Version Releases (Auto-Tagging)

We use `bump-my-version` to manage versions in `pyproject.toml` and automatically create Git tags.

### Bumping the Version
Before running these commands, ensure all your current changes are committed to git (`git commit -m "..."`).

* **Patch Release** (e.g., `3.0.0` ➔ `3.0.1` for bug fixes):
  ```bash
  uv run bump-my-version bump patch
  ```

* **Minor Release** (e.g., `3.0.0` ➔ `3.1.0` for new features/additions):
  ```bash
  uv run bump-my-version bump minor
  ```

* **Major Release** (e.g., `3.0.0` ➔ `4.0.0` for breaking changes/major overhauls):
  ```bash
  uv run bump-my-version bump major
  ```

### What Happens Automatically?
When you run the bump command, the tool will:
1. Parse the current version from `pyproject.toml`.
2. Increment the version according to the bump type.
3. Update `pyproject.toml` with the new version.
4. Create a Git commit: `Bump version: X.Y.Z → A.B.C`.
5. Create a Git tag: `vA.B.C`.

### Push to GitHub
After running the bump command, push the commit and the newly created tag to GitHub:
```bash
git push origin main --tags
```
