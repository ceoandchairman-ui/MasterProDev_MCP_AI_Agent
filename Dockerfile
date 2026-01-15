# Use Docker-in-Docker base image
FROM docker:24-dind

# Install docker-compose
RUN apk add --no-cache docker-compose python3

WORKDIR /app

# Copy entire project
COPY . .

# Expose ports
EXPOSE 8000 5432 6379 8080

# Start dockerd and run docker-compose
CMD ["sh", "-c", "dockerd-entrypoint.sh & sleep 2 && docker-compose up"]
