# SubWG2 Benchmarking Agent

This repo encodes knowhow about benchmarking the codes (mVMC and SALMON)
in SubWG2.

## Usage

Clone the repository, start Claude Code in the directory, and ask 
the agent for what you need. The skill in
.claude/skills/benchmark-generator handles the rest via uv.

Combining this repository with the HPC agents in the below repo should
allow for automatic experimentation.
```
https://github.com/RIKEN-RCCS/HPC-Agentic-SDK/tree/main
```

## Prerequisites

Requires [uv](https://docs.astral.sh/uv/). Install it if you don't have it:

```sh
# Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# macOS
brew install uv
```
