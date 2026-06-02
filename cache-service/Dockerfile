FROM golang:1.22 AS builder

WORKDIR /app

COPY go.mod go.sum ./
COPY . .
ENV GOPROXY=direct
RUN go mod download
RUN CGO_ENABLED=0 GOOS=linux go build -o cache-service .

FROM alpine:latest
WORKDIR /root/
COPY --from=builder /app/cache-service .
EXPOSE 8000
CMD ["./cache-service"]
