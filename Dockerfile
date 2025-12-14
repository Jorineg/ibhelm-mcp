FROM jorineg/ibhelm-base:latest

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py config.py auth.py database.py ./
COPY tools/ ./tools/

# Create non-root user
RUN useradd -m -u 1000 mcp && chown -R mcp:mcp /app
USER mcp

EXPOSE 8080

ENV SERVICE_NAME=mcp

CMD ["python", "server.py"]
