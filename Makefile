.PHONY: dev-db migrate test run ui clean-dev-db

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
	ANAMNESIS_MOCK_LLM=1 \
	DATABASE_URL=$${TEST_DATABASE_URL:-cockroachdb+psycopg://root@localhost:26257/anamnesis_test?sslmode=disable} \
	pytest tests/ -v

run:
	uvicorn app.main:app --reload --port 8000

ui:
	cd ui && python3 -m http.server 5173

clean-dev-db:
	docker rm -f anamnesis-crdb 2>/dev/null || true
