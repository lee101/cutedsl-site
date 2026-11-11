package main

import "testing"

func TestCompactHexPrefixRange(t *testing.T) {
	cases := []struct {
		token, lo, hi string
	}{
		{"055c8a31", "055c8a31", "055c8a32"},
		{"055c8a31a0074a20", "055c8a31-a007-4a20", "055c8a31-a007-4a21"},
		{"055c8a31a0074a20a78a", "055c8a31-a007-4a20-a78a", "055c8a31-a007-4a20-a78b"},
		{"055c8a31a0074a20a78a5a01f867d3d3", "055c8a31-a007-4a20-a78a-5a01f867d3d3", "055c8a31-a007-4a20-a78a-5a01f867d3d4"},
		{"055c8a3f", "055c8a3f", "055c8a40"},
	}
	for _, tc := range cases {
		lo, hi, ok := compactHexPrefixRange(tc.token)
		if !ok {
			t.Fatalf("token %q: expected ok", tc.token)
		}
		if lo != tc.lo || hi != tc.hi {
			t.Fatalf("token %q: got (%q,%q) want (%q,%q)", tc.token, lo, hi, tc.lo, tc.hi)
		}
	}
	if _, _, ok := compactHexPrefixRange("ffffffff"); ok {
		t.Fatal("all-f prefix should not produce a range")
	}
}

func TestCompactHexToUUIDPrefix(t *testing.T) {
	got := compactHexToUUIDPrefix("055c8a31a0074a20a78a5a01f867d3d3")
	want := "055c8a31-a007-4a20-a78a-5a01f867d3d3"
	if got != want {
		t.Fatalf("got %q want %q", got, want)
	}
}
