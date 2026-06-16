from dnsimple import Client as DNSimpleClient
from dnsimple.struct.zone_record import ZoneRecordInput

class DNSimpleARecord:
    @classmethod
    def create(cls, api_token, account_id, domain, subdomain, ip):
        client = DNSimpleClient(access_token=api_token)
        record = client.zones.create_record(
            account_id, domain,
            ZoneRecordInput(subdomain, type='A', content=ip, ttl=60)
        )
        return cls(client, account_id, domain, subdomain, record.data.id)
    def __init__(self, client, account_id, domain, subdomain, record_id):
        self.client = client
        self.account_id = account_id
        self.domain = domain
        self.subdomain = subdomain
        self.record_id = record_id
    def delete(self):
        self.client.zones.delete_record(
            self.account_id, self.domain, self.record_id
        )
    def __str__(self):
        return f'{self.subdomain}.{self.domain}'
