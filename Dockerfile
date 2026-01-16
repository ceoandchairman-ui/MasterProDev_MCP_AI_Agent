FROM docker:24-dind

# Install Python and dependencies
RUN apk add --no-cache python3 py3-pip docker-compose

WORKDIR /app

# Copy entire project
COPY . .

# Copy and make entrypoint executable
COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose ports
EXPOSE 8000 5432 6379 8080

# Use entrypoint script
ENTRYPOINT ["/entrypoint.sh"]
