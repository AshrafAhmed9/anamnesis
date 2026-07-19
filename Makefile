.PHONY: dev-db migrate test run ui clean-dev-db benchmark scale-test multinode-up multinode-init node-kill-demo multinode-down concurrency-test mvcc-demo changefeed-demo network-partition-demo

dev-db:
	docker rm -f anamnesis-crdb 2>/dev/null || true
	docker run -d --name anamnesis-crdb -p 26257:26257 -p 8090:8080 \
		cockroachdb/cockroach:latest-v25.2 start-single-node --insecure
	sleep 5
	docker exec anamnesis-crdb ./cockroach sql --insecure -e "CREATE DATABASE IF NOT EXISTS anamnesis;"
	docker exec anamnesis-crdb ./cockroach sql --insecure -e "SET CLUSTER SETTING feature.vector_index.enabled = true;"

migrate:
	DATABASE_URL=$${DATABASE_URL:-cockroachdb+psycopg://root@localhost:26257/anamnesis?sslmode=disable} alembic upgrade head

test:
	docker exec anamnesis-crdb ./cockroach sql --insecure -e "CREATE DATABASE IF NOT EXISTS anamnesis_test;"
	ANAMNESIS_MOCK_LLM=1 \
	DATABASE_URL=$${TEST_DATABASE_URL:-cockroachdb+psycopg://root@localhost:26257/anamnesis_test?sslmode=disable} \
	pytest tests/ -v

run:
	uvicorn app.main:app --reload --port 8000

ui:
	cd ui && python3 -m http.server 5173

clean-dev-db:
	docker rm -f anamnesis-crdb 2>/dev/null || true

# --- Quantified results (see SUBMISSION.md) ---

benchmark:
	docker exec anamnesis-crdb ./cockroach sql --insecure -e "CREATE DATABASE IF NOT EXISTS anamnesis_bench_single;"
	python3 scripts/benchmark.py

scale-test:
	docker exec anamnesis-crdb ./cockroach sql --insecure -e "CREATE DATABASE IF NOT EXISTS anamnesis_scale;"
	DATABASE_URL=cockroachdb+psycopg://root@localhost:26257/anamnesis_scale?sslmode=disable \
		alembic upgrade head
	python3 scripts/scale_test.py --rows 20000 --queries 100

multinode-up:
	docker compose -f infra/docker-compose.multinode.yml up -d
	sleep 5
	docker exec infra-crdb-1-1 ./cockroach init --insecure || true
	sleep 3
	docker exec infra-crdb-1-1 ./cockroach sql --insecure -e "CREATE DATABASE IF NOT EXISTS anamnesis_bench;"
	docker exec infra-crdb-1-1 ./cockroach sql --insecure -e "SET CLUSTER SETTING feature.vector_index.enabled = true;"
	DATABASE_URL=cockroachdb+psycopg://root@localhost:26258/anamnesis_bench?sslmode=disable \
		alembic upgrade head

node-kill-demo:
	python3 scripts/node_kill_demo.py

network-partition-demo:
	python3 scripts/network_partition_demo.py

multinode-down:
	docker compose -f infra/docker-compose.multinode.yml down

concurrency-test:
	docker exec anamnesis-crdb ./cockroach sql --insecure -e "CREATE DATABASE IF NOT EXISTS anamnesis_concurrency;"
	python3 scripts/concurrency_test.py --workers 10 --topic-count 3

mvcc-demo:
	python3 scripts/mvcc_timetravel_demo.py

changefeed-demo:
	docker exec anamnesis-crdb ./cockroach sql --insecure -e "SET CLUSTER SETTING kv.rangefeed.enabled = true;"
	python3 scripts/changefeed_demo.py
