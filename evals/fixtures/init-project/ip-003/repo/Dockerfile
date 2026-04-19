FROM golang:1.22 AS build
WORKDIR /src
COPY . .
RUN go build -o /out/mysvc ./

FROM gcr.io/distroless/base-debian12
COPY --from=build /out/mysvc /mysvc
ENTRYPOINT ["/mysvc"]
