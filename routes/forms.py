from django import forms
from .models import Route, Point, Edge 

class PointForm(forms.ModelForm):
    class Meta:
        model = Point
        fields = ['x', 'y']

class EdgeForm(forms.ModelForm):
    class Meta:
        model = Edge
        fields = ['start_point', 'end_point']
    
    def __init__(self, route, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['start_point'].queryset = Point.objects.filter(route=route)
        self.fields['end_point'].queryset = Point.objects.filter(route=route)

class RouteStyleForm(forms.ModelForm):
    class Meta:
        model = Route
        fields = ['vertex_color', 'vertex_text_color', 'edge_color']
        widgets = {
            'vertex_color': forms.TextInput(attrs={'type': 'color'}),
            'vertex_text_color': forms.TextInput(attrs={'type': 'color'}),
            'edge_color': forms.TextInput(attrs={'type': 'color'}),
        }
        

