from cbok.apps.alert import crawler


class AlertManager(object):
    def __init__(self) -> None:
        self.google_crawler = crawler.GoogleAlertCrawler()

    def _do_crawl_history(self, topic, first_track=False):
        date = 7 if first_track else 1
        history = self.google_crawler.analysis_history(topic, date)
        return history

    def crawl(self, topic, first_track=False):
        history = self._do_crawl_history(topic, first_track)

        for h in history:
            url = h["url"]
            if self.google_crawler.dedup(topic, url):
                continue

            article_content = self.google_crawler.fetch_article(h["url"])

            # TODO: write to database

    def derive(self, email):
        # get topic by email
        # get has updates topic
        # get not been derived article
        # ask AI and generate Question and EvolvingAnswerForActiveQuestion
        pass

    def notify(self, email, topic):
        # notify according to EvolvingAnswerForActiveQuestion
        pass
