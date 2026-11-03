import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from geocode import Address, Nominatim, parse_address


def test_parse_takes_the_city_state_and_upper_case_code():
    address = parse_address(
        {
            "city": "München",
            "state": "Bayern",
            "country": "Deutschland",
            "country_code": "de",
        }
    )

    assert address == Address(
        city="München", state="Bayern", country="Deutschland", country_code="DE"
    )


def test_parse_takes_the_town_when_there_is_no_city_and_the_county_for_the_state():
    address = parse_address({"town": "Wedel", "county": "Kreis Pinneberg"})

    assert (address.city, address.state) == ("Wedel", "Kreis Pinneberg")


def test_parse_makes_a_city_state_its_own_state():
    address = parse_address({"city": "Hamburg", "state_district": "Altona"})

    assert address.state == "Hamburg"


def test_parse_of_nothing_is_an_empty_address():
    assert parse_address({}) == Address()


@pytest.fixture
def nominatim_stub():
    """A local server that answers like Nominatim and records the requests."""
    requests = []
    answer = {"body": {"address": {"city": "Hamburg", "country_code": "de"}}}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((urlparse(self.path), self.headers))
            body = json.dumps(answer["body"]).encode()
            self.send_response(answer.get("status", 200))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/reverse"
    yield url, requests, answer
    server.shutdown()


def test_reverse_asks_in_german_and_names_itself(nominatim_stub):
    url, requests, _ = nominatim_stub
    nominatim = Nominatim(url, email="hbg@example.org")

    address = nominatim.reverse(53.55, 9.99)

    assert address.city == "Hamburg"
    assert address.country_code == "DE"
    [(request, headers)] = requests
    params = parse_qs(request.query)
    assert params["accept-language"] == ["de"]
    assert params["lat"] == ["53.55"]
    assert params["email"] == ["hbg@example.org"]
    assert "HBG-Sticker-API" in headers["User-Agent"]


def test_reverse_gives_an_empty_address_at_sea(nominatim_stub):
    url, _, answer = nominatim_stub
    answer["body"] = {"error": "Unable to geocode"}

    assert Nominatim(url, email="").reverse(0, -30) == Address()


def test_reverse_gives_an_empty_address_on_errors(nominatim_stub):
    url, _, answer = nominatim_stub
    answer["status"] = 503

    assert Nominatim(url, email="").reverse(0, 0) == Address()


def test_reverse_gives_an_empty_address_when_unreachable():
    assert Nominatim("http://127.0.0.1:9/reverse", email="").reverse(0, 0) == Address()


def test_reverse_waits_a_second_between_requests(nominatim_stub, monkeypatch):
    url, _, _ = nominatim_stub
    slept = []
    monkeypatch.setattr("geocode.time.sleep", slept.append)
    nominatim = Nominatim(url, email="")

    nominatim.reverse(0, 0)
    nominatim.reverse(0, 0)

    assert slept[0] == 0
    assert 0.9 < slept[1] <= 1
