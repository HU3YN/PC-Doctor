# Build from the repository root:  docker build -f upload-service/Dockerfile .
FROM golang:1.27-alpine@sha256:eb61c3873c97416fff0116553fff65d67a3549f72e11d9758849a689cdd8b523 AS build
WORKDIR /src
COPY upload-service/go.mod upload-service/go.sum ./
RUN go mod download
COPY upload-service/*.go ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /upload-service . \
    && mkdir -m 1777 /empty-tmp

# Nothing in the final image but the program: no shell, no package manager.
FROM scratch
COPY --from=build /upload-service /upload-service
# Large form uploads are spooled to the temp folder while they are read.
COPY --from=build /empty-tmp /tmp
# The same user id as the API image, so both can use the shared data volume.
USER 10001
ENV PCDOCTOR_SPOOL_DIR=/data/spool
EXPOSE 8090
ENTRYPOINT ["/upload-service"]
