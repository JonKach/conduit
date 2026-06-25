#! /usr/bin/env bash

set -e
set -x

# Let the DB start
python app/backend_pre_start.py

# Run migrations
alembic upgrade head

# Initialize LangGraph components
python app/langgraph_store_setup.py

# Create initial data in DB
python app/initial_data.py
