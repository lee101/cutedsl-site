package main

import (
	"errors"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/valyala/fasthttp"
)

var mediaProxyClient = &http.Client{
	Timeout: 15 * time.Minute,
	CheckRedirect: func(req *http.Request, _ []*http.Request) error {
		_, err := allowedMediaProxyURL(req.URL.String())
		return err
	},
}

func allowedMediaProxyURL(raw string) (*url.URL, error) {
	parsed, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || parsed.Scheme != "https" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" {
		return nil, errors.New("invalid media URL")
	}
	if parsed.Port() != "" && parsed.Port() != "443" {
		return nil, errors.New("invalid media port")
	}
	host := strings.ToLower(parsed.Hostname())
	allowed := host == "manifoldgenstatic.manifoldgen.com" ||
		host == "appstatic.app.nz" || host == "cutedsl.cc" || host == "www.cutedsl.cc"
	if !allowed {
		return nil, errors.New("media host is not allowed")
	}
	if parsed.Path == "" || parsed.Path == "/" {
		return nil, errors.New("media path is required")
	}
	return parsed, nil
}

func handleMediaProxy(ctx *fasthttp.RequestCtx) {
	parsed, err := allowedMediaProxyURL(string(ctx.QueryArgs().Peek("url")))
	if err != nil {
		jsonError(ctx, http.StatusBadRequest, err.Error())
		return
	}
	method := string(ctx.Method())
	if method != http.MethodGet && method != http.MethodHead {
		jsonError(ctx, http.StatusMethodNotAllowed, "GET or HEAD required")
		return
	}
	request, err := http.NewRequest(method, parsed.String(), nil)
	if err != nil {
		jsonError(ctx, http.StatusBadRequest, "invalid media request")
		return
	}
	request.Header.Set("User-Agent", "Mozilla/5.0 CuteDSL-MediaEditor/1.0")
	if rangeHeader := string(ctx.Request.Header.Peek("Range")); rangeHeader != "" {
		request.Header.Set("Range", rangeHeader)
	}
	response, err := mediaProxyClient.Do(request)
	if err != nil {
		jsonError(ctx, http.StatusBadGateway, "media source unavailable")
		return
	}
	if response.StatusCode < 200 || response.StatusCode >= 400 {
		response.Body.Close()
		jsonError(ctx, http.StatusBadGateway, "media source rejected the request")
		return
	}

	for _, name := range []string{"Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "ETag", "Last-Modified"} {
		if value := response.Header.Get(name); value != "" {
			ctx.Response.Header.Set(name, value)
		}
	}
	ctx.Response.Header.Set("Cache-Control", "public, max-age=3600, stale-while-revalidate=86400")
	ctx.Response.Header.Set("X-Content-Type-Options", "nosniff")
	ctx.SetStatusCode(response.StatusCode)
	if method == http.MethodHead {
		response.Body.Close()
		return
	}
	bodySize := -1
	if response.ContentLength >= 0 && response.ContentLength <= int64(^uint(0)>>1) {
		bodySize = int(response.ContentLength)
	}
	ctx.Response.SetBodyStream(io.ReadCloser(response.Body), bodySize)
}
