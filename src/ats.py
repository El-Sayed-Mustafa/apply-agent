"""
مواقع التقديم اللي بنقرا فورمها: Ashby و Greenhouse و Lever.

كل موقع ليه نفس الوش: parse_url · application_url · form · unsupported.
الباقي (موقع الشركة، Workday…) بيروح "قدّم بنفسك" بالملف الجاهز.
"""
from __future__ import annotations

from . import ashby, greenhouse, lever


def site_of(url: str | None, company: str | None = None) -> str | None:
    if ashby.parse_url(url):
        return "ashby"
    if greenhouse.parse_url(url, company):
        return "greenhouse"
    if lever.parse_url(url):
        return "lever"
    return None


def posting_key(url: str | None, company: str | None = None) -> tuple[str, str] | None:
    """(الموقع، رقم الإعلان) — نفس الإعلان من أي لينك ليه (البورد، الـembed، /apply)."""
    site = site_of(url, company)
    if site == "ashby":
        org, jid = ashby.parse_url(url)
        return site, f"{org.lower()}/{jid}"
    if site == "greenhouse":
        return site, greenhouse.parse_url(url, company)[1]
    if site == "lever":
        return site, lever.parse_url(url)[2]
    return None


def form(url: str, company: str | None = None) -> list[dict] | None:
    site = site_of(url, company)
    if site == "ashby":
        return ashby.form(url)
    if site == "greenhouse":
        return greenhouse.form(url, company)
    if site == "lever":
        return lever.form(url)
    return None


def application_url(url: str, company: str | None = None) -> str:
    site = site_of(url, company)
    if site == "ashby":
        return ashby.application_url(url)
    if site == "greenhouse":
        return greenhouse.application_url(url, company)
    if site == "lever":
        return lever.application_url(url)
    return url


def unsupported(site: str, fields: list[dict]) -> list[dict]:
    return {"ashby": ashby, "greenhouse": greenhouse, "lever": lever}[site].unsupported(fields)
