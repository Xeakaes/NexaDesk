from core.events import EventBus, Event

def test_publish_delivers_with_ids():
    bus = EventBus(); seen = []
    bus.subscribe("agent_started", seen.append)
    bus.publish("agent_started", "s1", "t1", {"user_text": "hi"})
    assert seen == [Event("agent_started", "s1", "t1", {"user_text": "hi"})]

def test_wildcard_receives_all():
    bus = EventBus(); names = []
    bus.subscribe("*", lambda e: names.append(e.name))
    bus.publish("a", "s", "t", {}); bus.publish("b", "s", "t", {})
    assert names == ["a", "b"]

def test_unsubscribe_stops_delivery():
    bus = EventBus(); seen = []
    cb = seen.append
    bus.subscribe("x", cb); bus.unsubscribe("x", cb)
    bus.publish("x", "s", "t", {})
    assert seen == []

def test_bad_subscriber_does_not_kill_the_dispatch_loop():
    # B20: one subscriber raising must neither propagate into the publisher
    # nor drop the event for every later subscriber.
    bus = EventBus()
    seen = []

    def bad(e):
        raise RuntimeError("boom")

    bus.subscribe("x", bad)
    bus.subscribe("x", seen.append)
    bus.publish("x", "s", "t", {})
    assert seen == [Event("x", "s", "t", {})]

def test_bad_wildcard_subscriber_does_not_block_named_ones():
    bus = EventBus()
    seen = []
    bus.subscribe("*", lambda e: 1 / 0)
    bus.subscribe("x", seen.append)
    bus.publish("x", "s", "t", {})
    assert seen == [Event("x", "s", "t", {})]

def test_bad_subscriber_error_is_logged(monkeypatch):
    import core.events as ev

    logged = []
    monkeypatch.setattr(
        ev, "log_event", lambda name, **kw: logged.append((name, kw))
    )
    bus = EventBus()
    bus.subscribe("x", lambda e: (_ for _ in ()).throw(ValueError("boom")))
    bus.publish("x", "s", "t", {})
    assert logged and logged[0][0] == "subscriber_error"
    assert logged[0][1]["event_name"] == "x"

def test_event_name_list_matches_spec():
    from core.events import EVENT_NAMES
    assert set(EVENT_NAMES) >= {
        "agent_started", "assistant_message", "tool_started", "tool_finished",
        "confirmation_requested", "agent_error", "agent_finished", "agent_cancelled"}
