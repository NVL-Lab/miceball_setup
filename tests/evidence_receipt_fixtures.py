"""JetStream state double for public evidence-receipt workflows."""

from datetime import datetime, timezone
from types import SimpleNamespace
from nats.js.api import ConsumerInfo, RetentionPolicy, SequenceInfo, StorageType, StreamConfig, StreamInfo, StreamState
from nats.js.errors import NotFoundError


class EvidenceReceiptBroker:
    def __init__(self):
        self.created = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.records = {}
        self.last_sequence = 0
        self.consumers = {}
        self.callbacks = {}
        self.acknowledged = {}
        self.deliveries = {}
        self.unavailable = False

    async def stream_info(self, name):
        if self.unavailable:
            raise ConnectionError("broker unavailable")
        sequences = sorted(self.records)
        first = sequences[0] if sequences else self.last_sequence + 1 if self.last_sequence else 0
        return StreamInfo(
            config=StreamConfig(name=name, storage=StorageType.FILE, retention=RetentionPolicy.LIMITS),
            created=self.created,
            state=StreamState(messages=len(sequences), bytes=0, first_seq=first,
                              last_seq=self.last_sequence, consumer_count=len(self.consumers),
                              num_deleted=self.last_sequence - len(sequences) if first <= 1 else 0),
        )

    async def consumer_info(self, stream, durable):
        if durable not in self.consumers:
            raise NotFoundError
        return self.consumers[durable]

    def register(self, subject, options):
        config, durable = options.get("config"), options.get("durable")
        if durable and durable not in self.consumers:
            self.consumers[durable] = ConsumerInfo(
                name=durable, stream_name=options["stream"], config=config,
                created=self.created, delivered=SequenceInfo(0, 0),
                ack_floor=SequenceInfo(0, 0), num_ack_pending=0,
            )
            self.acknowledged[durable] = set()
            self.deliveries[durable] = {}

    async def subscribe(self, subject, cb, **options):
        self.register(subject, options)
        self.callbacks[options.get("durable")] = cb
        return SimpleNamespace(unsubscribe=self.unsubscribe)

    async def unsubscribe(self):
        self.callbacks.clear()

    async def publish(self, subject, data, stream="LAB_EVIDENCE"):
        self.last_sequence += 1
        self.records[self.last_sequence] = SimpleNamespace(subject=subject, data=data, seq=self.last_sequence)
        return SimpleNamespace(stream=stream, seq=self.last_sequence)

    async def get_last_msg(self, stream, subject):
        matches = [record for record in self.records.values() if record.subject == subject]
        if not matches:
            raise NotFoundError
        return matches[-1]

    async def get_msg(self, stream, seq=None, subject=None, next=False):
        if self.unavailable:
            raise ConnectionError("broker unavailable")
        for sequence in sorted(self.records):
            record = self.records[sequence]
            if (sequence >= seq and (next or sequence == seq)
                    and (subject is None or all(
                        wanted == "*" or wanted == actual
                        for wanted, actual in zip(subject.split("."), record.subject.split(".")))
                        and len(subject.split(".")) == len(record.subject.split(".")))):
                return record
        raise NotFoundError

    async def deliver(self, durable, sequence, *, acknowledge=True):
        consumer, record = self.consumers[durable], self.records[sequence]
        number = consumer.delivered.consumer_seq + 1
        self.deliveries[durable][number] = sequence
        consumer.delivered = SequenceInfo(number, sequence)
        consumer.num_ack_pending += 1

        async def ack_sync():
            if not acknowledge:
                raise ConnectionError("ACK confirmation unavailable")
            self.acknowledged[durable].update(
                delivery for delivery, stream_sequence in self.deliveries[durable].items()
                if stream_sequence == sequence)
            floor = consumer.ack_floor.consumer_seq
            while floor + 1 in self.acknowledged[durable]:
                floor += 1
            consumer.ack_floor = SequenceInfo(floor, self.deliveries[durable].get(floor, 0))
            consumer.num_ack_pending -= 1

        await self.callbacks[durable](SimpleNamespace(data=record.data, ack_sync=ack_sync))
