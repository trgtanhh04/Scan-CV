# Use official Qdrant image as base
FROM qdrant/qdrant:v1.11.0

# Copy our Cloud Run-friendly entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose port 8080 for Cloud Run
EXPOSE 8080

# Use entrypoint
ENTRYPOINT ["/entrypoint.sh"]
