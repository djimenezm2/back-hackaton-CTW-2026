from django.urls import path

from ayudagente.radar import views

app_name = 'radar'

urlpatterns = [
    path('events/', views.event_list, name='event-list'),
    path('events/<int:event_id>/graph/', views.event_graph, name='event-graph'),
]
