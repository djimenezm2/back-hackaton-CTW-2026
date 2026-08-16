from django.urls import path

from ayudagente.radar import agent_views, views

app_name = "radar"

urlpatterns = [
    path("events/", views.event_list, name="event-list"),
    path("events/<int:event_id>/graph/", views.event_graph, name="event-graph"),
    path("agent/coordination/", agent_views.coordination_agent, name="agent-coordination"),
    path("agent/frontier/", agent_views.frontier_agent, name="agent-frontier"),
]
