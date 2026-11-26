import anyio
import httpx2
import pytest

from tests.docs.support.docs_site import DocsSite


class TestDocsSite:
    path = '/page.html'
    body = b'0123456789' * 100
    url = f'https://docs.python.org{path}'

    @pytest.fixture
    def plain_site(self) -> DocsSite:
        return DocsSite(pages={self.path: self.body})

    @pytest.fixture
    def held_site(self) -> DocsSite:
        return DocsSite(pages={self.path: self.body}, held=frozenset({self.path}))

    async def download(self, site: DocsSite) -> bytes:
        async with httpx2.AsyncClient(transport=site.transport()) as client:
            response = await client.get(self.url)
        return response.content

    async def test_unheld_site_serves_the_full_body(self, plain_site: DocsSite) -> None:
        assert await self.download(plain_site) == self.body

    async def test_held_download_waits_for_release_then_delivers_the_full_body(
        self, held_site: DocsSite
    ) -> None:
        received: list[bytes] = []

        async def run_download() -> None:
            received.append(await self.download(held_site))

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(run_download)
            with anyio.fail_after(5):
                await held_site.wait_until_held()
            await anyio.sleep(0.05)
            assert received == []
            held_site.release()
        assert received == [self.body]
