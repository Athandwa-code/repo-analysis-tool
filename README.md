# Repo Analysis Tool (RAT)

A web dashboard that analyzes git repositories and visualizes how they evolved:
who had the most impact where, and which files and directories are the most volatile.

## Planned Features

- **Repository ingestion**: upload a zip of the repo (including the `.git` folder), or provide a remote URL for a full clone
- **Multiple repositories** in one dashboard
- **Author merging** via `.mailmap`, or manual merging in the UI when none is provided
- **Metrics** for files, directories, the repository, commit sets, and authors:
  - added lines, removed lines, growth, churn
  - modifications, modification frequency, churn rate
  - author modifications, author churn, ownership
- **Filters**: repository, author, file/directory, and commit sets (time range or a manually selected list of commits)

## Status

In development.

## Running the App

Setup instructions will be added here as the project comes together.
