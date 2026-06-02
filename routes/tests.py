import json
from pathlib import Path
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.contrib.staticfiles import finders
from django.urls import reverse
from PIL import Image

from .models import BackgroundImage, Drawing, DrawingObject, Edge, Point, Route


TEST_MEDIA_ROOT = tempfile.mkdtemp()


def create_test_image(name="background.png", size=(200, 100)):
    image = Image.new("RGB", size, color="white")
    buffer = tempfile.SpooledTemporaryFile()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    content = buffer.read()
    buffer.close()
    image.close()
    return SimpleUploadedFile(name, content, content_type="image/png")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class RouteViewsTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="password123")
        self.other_user = User.objects.create_user(username="bob", password="password123")
        self.background = BackgroundImage.objects.create(
            title="Test background",
            image=create_test_image(),
        )
        self.route = Route.objects.create(
            user=self.user,
            title="Alice route",
            background=self.background,
        )
        self.other_route = Route.objects.create(
            user=self.other_user,
            title="Bob route",
            background=self.background,
        )

    def login(self):
        self.client.login(username="alice", password="password123")

    def test_route_list_contains_only_current_user_routes(self):
        self.login()

        response = self.client.get(reverse("route_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice route")
        self.assertNotContains(response, "Bob route")

    def test_route_detail_is_restricted_to_owner(self):
        self.login()

        own_response = self.client.get(reverse("route_detail", kwargs={"pk": self.route.pk}))
        other_response = self.client.get(reverse("route_detail", kwargs={"pk": self.other_route.pk}))

        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(other_response.status_code, 404)

    def test_add_point_ajax_returns_json_and_creates_point(self):
        self.login()

        response = self.client.post(
            reverse("add_point", kwargs={"route_id": self.route.pk}),
            {"x": "25", "y": "30"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertJSONEqual(
            response.content,
            {
                "success": True,
                "point": {
                    "id": Point.objects.get(route=self.route).id,
                    "x": 25,
                    "y": 30,
                    "order": 1,
                },
            },
        )
        self.assertEqual(self.route.points.count(), 1)

    def test_add_point_rejects_invalid_coordinates_for_ajax(self):
        self.login()

        response = self.client.post(
            reverse("add_point", kwargs={"route_id": self.route.pk}),
            {"x": "abc", "y": "30"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.route.points.count(), 0)
        self.assertFalse(response.json()["success"])

    def test_add_edge_creates_edge_for_points_from_same_route(self):
        self.login()
        point_a = Point.objects.create(route=self.route, x=10, y=10, order=1)
        point_b = Point.objects.create(route=self.route, x=90, y=10, order=2)

        response = self.client.post(
            reverse("add_edge", kwargs={"route_id": self.route.pk}),
            {"start_point": point_a.pk, "end_point": point_b.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertTrue(
            Edge.objects.filter(route=self.route, start_point=point_a, end_point=point_b).exists()
        )

    def test_add_edge_rejects_same_start_and_end_point(self):
        self.login()
        point = Point.objects.create(route=self.route, x=10, y=10, order=1)

        response = self.client.post(
            reverse("add_edge", kwargs={"route_id": self.route.pk}),
            {"start_point": point.pk, "end_point": point.pk},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertEqual(Edge.objects.count(), 0)

    def test_add_edge_rejects_point_from_another_users_route(self):
        self.login()
        own_point = Point.objects.create(route=self.route, x=10, y=10, order=1)
        foreign_point = Point.objects.create(route=self.other_route, x=90, y=10, order=1)

        response = self.client.post(
            reverse("add_edge", kwargs={"route_id": self.route.pk}),
            {"start_point": own_point.pk, "end_point": foreign_point.pk},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertEqual(Edge.objects.count(), 0)

    def test_delete_point_renumbers_remaining_points(self):
        self.login()
        point_1 = Point.objects.create(route=self.route, x=10, y=10, order=1)
        point_2 = Point.objects.create(route=self.route, x=20, y=20, order=2)
        point_3 = Point.objects.create(route=self.route, x=30, y=30, order=3)

        response = self.client.post(reverse("delete_point", kwargs={"pk": point_2.pk}))

        self.assertRedirects(response, reverse("route_detail", kwargs={"pk": self.route.pk}))
        self.assertFalse(Point.objects.filter(pk=point_2.pk).exists())
        self.assertEqual(list(self.route.points.order_by("order").values_list("id", "order")), [(point_1.id, 1), (point_3.id, 2)])

    def test_update_route_style_changes_only_owner_route(self):
        self.login()

        response = self.client.post(
            reverse("update_route_style", kwargs={"route_id": self.route.pk}),
            {
                "vertex_color": "#111111",
                "vertex_text_color": "#eeeeee",
                "edge_color": "#123456",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.route.refresh_from_db()
        self.assertEqual(self.route.vertex_color, "#111111")
        self.assertEqual(self.route.vertex_text_color, "#eeeeee")
        self.assertEqual(self.route.edge_color, "#123456")

    def test_export_latex_contains_nodes_and_edges(self):
        self.login()
        point_a = Point.objects.create(route=self.route, x=10, y=10, order=1)
        point_b = Point.objects.create(route=self.route, x=90, y=10, order=2)
        Edge.objects.create(route=self.route, start_point=point_a, end_point=point_b)

        response = self.client.get(reverse("export_latex", kwargs={"route_id": self.route.pk}))
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("\\begin{tikzpicture}", content)
        self.assertIn("\\node[node] (1)", content)
        self.assertIn("(1) edge[edge] (2)", content)

    def test_export_png_returns_png_file(self):
        self.login()
        Point.objects.create(route=self.route, x=10, y=10, order=1)

        response = self.client.get(reverse("export_png", kwargs={"route_id": self.route.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG"))



@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DrawingModelAndViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="password123")
        self.other_user = User.objects.create_user(username="bob", password="password123")
        self.drawing = Drawing.objects.create(
            user=self.user,
            title="Alice structured drawing",
            mode=Drawing.MODE_MIXED,
            metadata={"schema_version": 1},
        )
        self.other_drawing = Drawing.objects.create(
            user=self.other_user,
            title="Bob structured drawing",
            mode=Drawing.MODE_GEOMETRY,
        )

    def login(self):
        self.client.login(username="alice", password="password123")

    def test_drawing_can_store_structured_objects(self):
        obj = DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="v1",
            type="graph.vertex",
            data={"x": 100, "y": 150, "label": "v_1"},
            style={"stroke": "#000000", "fill": "#ffffff"},
            order=1,
        )

        self.assertEqual(obj.drawing, self.drawing)
        self.assertEqual(obj.data["label"], "v_1")
        self.assertEqual(obj.style["fill"], "#ffffff")
        self.assertEqual(list(self.drawing.drawing_objects.all()), [obj])

    def test_drawing_object_ids_must_be_unique_inside_one_drawing(self):
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="obj_1",
            type="graph.vertex",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DrawingObject.objects.create(
                    drawing=self.drawing,
                    object_id="obj_1",
                    type="graph.edge",
                )

        # Ten sam object_id może istnieć w innym rysunku.
        other = DrawingObject.objects.create(
            drawing=self.other_drawing,
            object_id="obj_1",
            type="geometry.point",
        )
        self.assertEqual(other.object_id, "obj_1")

    def test_deleting_drawing_deletes_its_objects(self):
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="v1",
            type="graph.vertex",
        )

        self.drawing.delete()

        self.assertEqual(DrawingObject.objects.count(), 0)

    def test_drawing_list_contains_only_current_user_drawings(self):
        self.login()

        response = self.client.get(reverse("drawing_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice structured drawing")
        self.assertNotContains(response, "Bob structured drawing")

    def test_drawing_detail_is_restricted_to_owner(self):
        self.login()

        own_response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))
        foreign_response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.other_drawing.pk}))

        self.assertEqual(own_response.status_code, 200)
        self.assertContains(own_response, "Alice structured drawing")
        self.assertEqual(foreign_response.status_code, 404)

    def test_drawing_detail_contains_canvas_editor_and_api_url(self):
        self.login()

        response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-drawing-editor")
        self.assertContains(response, "data-role=\"drawing-canvas\"")
        self.assertContains(response, reverse("drawing_objects_collection", kwargs={"drawing_id": self.drawing.pk}))
        self.assertContains(response, "routes/drawing_editor.js")
        self.assertContains(response, "routes/drawing_editor.css")
        self.assertContains(response, "graph.vertex łączymy tylko krawędziami grafowymi")

    def test_drawing_editor_static_files_are_available(self):
        self.assertIsNotNone(finders.find("routes/drawing_editor.js"))
        self.assertIsNotNone(finders.find("routes/drawing_editor.css"))

    def test_create_drawing_sets_current_user_and_metadata(self):
        self.login()

        response = self.client.post(
            reverse("drawing_create"),
            {"title": "New geometry drawing", "mode": Drawing.MODE_GEOMETRY},
        )

        drawing = Drawing.objects.get(title="New geometry drawing")
        self.assertRedirects(response, reverse("drawing_detail", kwargs={"pk": drawing.pk}))
        self.assertEqual(drawing.user, self.user)
        self.assertEqual(drawing.mode, Drawing.MODE_GEOMETRY)
        self.assertEqual(drawing.metadata["schema_version"], 1)

    def test_delete_drawing_is_restricted_to_owner(self):
        self.login()

        foreign_response = self.client.post(reverse("drawing_delete", kwargs={"pk": self.other_drawing.pk}))
        own_response = self.client.post(reverse("drawing_delete", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(foreign_response.status_code, 404)
        self.assertRedirects(own_response, reverse("drawing_list"))
        self.assertFalse(Drawing.objects.filter(pk=self.drawing.pk).exists())
        self.assertTrue(Drawing.objects.filter(pk=self.other_drawing.pk).exists())

    def test_drawing_objects_api_creates_object_from_json(self):
        self.login()

        response = self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": self.drawing.pk}),
            data=json.dumps({
                "object_id": "v1",
                "type": "graph.vertex",
                "data": {"x": 100, "y": 150, "label": "v_1"},
                "style": {"fill": "#ffffff", "stroke": "#000000"},
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["success"])
        obj = DrawingObject.objects.get(drawing=self.drawing, object_id="v1")
        self.assertEqual(obj.type, "graph.vertex")
        self.assertEqual(obj.data["label"], "v_1")
        self.assertEqual(obj.order, 0)

    def test_drawing_objects_api_can_generate_object_id(self):
        self.login()

        response = self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": self.drawing.pk}),
            data=json.dumps({
                "type": "geometry.point",
                "data": {"x": 10, "y": 20},
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        object_id = response.json()["object"]["object_id"]
        self.assertTrue(object_id.startswith("obj_"))
        self.assertTrue(DrawingObject.objects.filter(drawing=self.drawing, object_id=object_id).exists())

    def test_drawing_objects_api_lists_only_objects_from_owner_drawing(self):
        self.login()
        DrawingObject.objects.create(drawing=self.drawing, object_id="v1", type="graph.vertex")
        DrawingObject.objects.create(drawing=self.other_drawing, object_id="foreign", type="graph.vertex")

        response = self.client.get(reverse("drawing_objects_collection", kwargs={"drawing_id": self.drawing.pk}))
        foreign_response = self.client.get(reverse("drawing_objects_collection", kwargs={"drawing_id": self.other_drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual([obj["object_id"] for obj in response.json()["objects"]], ["v1"])
        self.assertEqual(foreign_response.status_code, 404)

    def test_drawing_objects_api_rejects_invalid_payload(self):
        self.login()

        response = self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": self.drawing.pk}),
            data=json.dumps({
                "type": "",
                "data": ["not", "an", "object"],
                "style": "not an object",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertIn("type", response.json()["errors"])
        self.assertIn("data", response.json()["errors"])
        self.assertIn("style", response.json()["errors"])
        self.assertEqual(DrawingObject.objects.filter(drawing=self.drawing).count(), 0)

    def test_drawing_objects_api_rejects_duplicate_object_id(self):
        self.login()
        DrawingObject.objects.create(drawing=self.drawing, object_id="v1", type="graph.vertex")

        response = self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": self.drawing.pk}),
            data=json.dumps({
                "object_id": "v1",
                "type": "graph.vertex",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("object_id", response.json()["errors"])

    def test_drawing_object_detail_api_gets_object(self):
        self.login()
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="v1",
            type="graph.vertex",
            data={"x": 1, "y": 2},
        )

        response = self.client.get(reverse(
            "drawing_object_detail",
            kwargs={"drawing_id": self.drawing.pk, "object_id": "v1"},
        ))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["object"]["type"], "graph.vertex")
        self.assertEqual(response.json()["object"]["data"], {"x": 1, "y": 2})

    def test_drawing_object_detail_api_patches_object(self):
        self.login()
        obj = DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="v1",
            type="graph.vertex",
            data={"x": 1, "y": 2},
            style={"fill": "white"},
        )

        response = self.client.patch(
            reverse("drawing_object_detail", kwargs={"drawing_id": self.drawing.pk, "object_id": "v1"}),
            data=json.dumps({"data": {"x": 10, "y": 20}, "style": {"fill": "red"}}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        obj.refresh_from_db()
        self.assertEqual(obj.data, {"x": 10, "y": 20})
        self.assertEqual(obj.style, {"fill": "red"})
        self.assertEqual(obj.type, "graph.vertex")


    def test_drawing_object_detail_api_patches_point_position_and_preserves_label(self):
        self.login()
        obj = DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="p1",
            type="geometry.point",
            data={"x": 10, "y": 20, "label": "A"},
            style={"fill": "#111827"},
        )

        response = self.client.patch(
            reverse("drawing_object_detail", kwargs={"drawing_id": self.drawing.pk, "object_id": "p1"}),
            data=json.dumps({"data": {"x": 80, "y": 90, "label": "A"}}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        obj.refresh_from_db()
        self.assertEqual(obj.data, {"x": 80, "y": 90, "label": "A"})
        self.assertEqual(response.json()["object"]["data"]["x"], 80)
        self.assertEqual(response.json()["object"]["data"]["y"], 90)

    def test_drawing_editor_static_js_contains_drag_and_patch_support(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("pointerdown", source)
        self.assertIn("handlePointerMove", source)
        self.assertIn("handlePointerUp", source)
        self.assertIn('method: "PATCH"', source)
        self.assertIn("setPointerCapture", source)

    def test_drawing_object_detail_api_put_replaces_object_fields(self):
        self.login()
        obj = DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="v1",
            type="graph.vertex",
            data={"x": 1},
            style={"fill": "white"},
        )

        response = self.client.put(
            reverse("drawing_object_detail", kwargs={"drawing_id": self.drawing.pk, "object_id": "v1"}),
            data=json.dumps({
                "type": "geometry.point",
                "data": {"x": 3, "y": 4},
                "style": {},
                "order": 5,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        obj.refresh_from_db()
        self.assertEqual(obj.type, "geometry.point")
        self.assertEqual(obj.data, {"x": 3, "y": 4})
        self.assertEqual(obj.style, {})
        self.assertEqual(obj.order, 5)

    def test_drawing_object_detail_api_deletes_object(self):
        self.login()
        DrawingObject.objects.create(drawing=self.drawing, object_id="v1", type="graph.vertex")

        response = self.client.delete(reverse(
            "drawing_object_detail",
            kwargs={"drawing_id": self.drawing.pk, "object_id": "v1"},
        ))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertFalse(DrawingObject.objects.filter(drawing=self.drawing, object_id="v1").exists())

    def test_drawing_object_detail_api_is_restricted_to_owner(self):
        self.login()
        DrawingObject.objects.create(drawing=self.other_drawing, object_id="foreign", type="graph.vertex")

        response = self.client.get(reverse(
            "drawing_object_detail",
            kwargs={"drawing_id": self.other_drawing.pk, "object_id": "foreign"},
        ))

        self.assertEqual(response.status_code, 404)

    def test_drawing_objects_api_can_store_segment_between_two_points(self):
        self.login()
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="p1",
            type="geometry.point",
            data={"x": 10, "y": 20, "label": "A"},
        )
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="p2",
            type="geometry.point",
            data={"x": 80, "y": 90, "label": "B"},
        )

        response = self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": self.drawing.pk}),
            data=json.dumps({
                "object_id": "s1",
                "type": "geometry.segment",
                "data": {"source": "p1", "target": "p2", "label": "AB"},
                "style": {"stroke": "#111827", "strokeWidth": 2},
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        segment = DrawingObject.objects.get(drawing=self.drawing, object_id="s1")
        self.assertEqual(segment.type, "geometry.segment")
        self.assertEqual(segment.data["source"], "p1")
        self.assertEqual(segment.data["target"], "p2")
        self.assertEqual(response.json()["object"]["data"]["label"], "AB")

    def test_drawing_detail_contains_segment_and_edge_tools(self):
        self.login()

        response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="geometry.segment"')
        self.assertContains(response, 'value="graph.edge.undirected"')
        self.assertContains(response, 'value="graph.edge.directed"')
        self.assertContains(response, "geometry.segment")
        self.assertContains(response, "graph.edge")

    def test_drawing_editor_static_js_contains_line_creation_support(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("geometry.segment", source)
        self.assertIn("graph.edge", source)
        self.assertIn("createLineBetweenPoints", source)
        self.assertIn("renderLine", source)
        self.assertIn("source", source)
        self.assertIn("target", source)



    def test_drawing_object_detail_api_patches_style(self):
        self.login()
        obj = DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="p1",
            type="geometry.point",
            data={"x": 10, "y": 20, "label": "A"},
            style={"fill": "#111827", "stroke": "#111827", "radius": 5},
        )

        response = self.client.patch(
            reverse("drawing_object_detail", kwargs={"drawing_id": self.drawing.pk, "object_id": "p1"}),
            data=json.dumps({
                "style": {
                    "fill": "#ff0000",
                    "stroke": "#0000ff",
                    "strokeWidth": 3,
                    "radius": 9,
                    "showLabel": False,
                }
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        obj.refresh_from_db()
        self.assertEqual(obj.style["fill"], "#ff0000")
        self.assertEqual(obj.style["stroke"], "#0000ff")
        self.assertEqual(obj.style["strokeWidth"], 3)
        self.assertEqual(obj.style["radius"], 9)
        self.assertFalse(obj.style["showLabel"])

    def test_drawing_detail_contains_style_panel(self):
        self.login()

        response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Styl zaznaczonego obiektu")
        self.assertContains(response, "data-role=\"style-stroke\"")
        self.assertContains(response, "data-role=\"style-fill\"")
        self.assertContains(response, "data-role=\"style-stroke-width\"")
        self.assertContains(response, "data-role=\"style-radius\"")
        self.assertContains(response, "data-role=\"style-show-label\"")

    def test_drawing_editor_static_js_contains_style_support(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("applySelectedStyle", source)
        self.assertIn("updateStylePanel", source)
        self.assertIn("style-show-label", source)
        self.assertIn("strokeWidth", source)
        self.assertIn("showLabel", source)

    def test_drawing_export_tikz_uses_styles_and_hidden_labels(self):
        self.login()
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="A",
            type="geometry.point",
            data={"x": 100, "y": 120, "label": "Hidden"},
            style={
                "fill": "#ff0000",
                "stroke": "#0000ff",
                "strokeWidth": 3,
                "radius": 10,
                "showLabel": False,
            },
        )
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="B",
            type="geometry.point",
            data={"x": 300, "y": 120, "label": "B"},
            style={"fill": "#111827", "stroke": "#111827", "showLabel": True},
        )
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="AB",
            type="geometry.segment",
            data={"source": "A", "target": "B", "label": "edge"},
            style={"stroke": "#00ff00", "strokeWidth": 4, "showLabel": False},
        )

        response = self.client.get(reverse("drawing_export_tikz", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("\\definecolor{mdeFF0000}{HTML}{FF0000}", content)
        self.assertIn("\\definecolor{mde0000FF}{HTML}{0000FF}", content)
        self.assertIn("line width=3pt", content)
        self.assertIn("circle (0.1cm)", content)
        self.assertIn("line width=4pt", content)
        self.assertNotIn("$ Hidden $", content)
        self.assertNotIn("$ edge $", content)

    def test_drawing_export_tikz_contains_points_segments_and_directed_edges(self):
        self.login()
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="A",
            type="geometry.point",
            data={"x": 100, "y": 120, "label": "A"},
        )
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="B",
            type="graph.vertex",
            data={"x": 300, "y": 120, "label": "B"},
        )
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="AB",
            type="geometry.segment",
            data={"source": "A", "target": "B", "label": "e"},
        )
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="BA",
            type="graph.edge",
            data={"source": "B", "target": "A", "label": "f"},
            style={"directed": True},
        )

        response = self.client.get(reverse("drawing_export_tikz", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        content = response.content.decode("utf-8")
        self.assertIn("\\begin{tikzpicture}", content)
        self.assertIn("\\coordinate (A)", content)
        self.assertIn("\\node[circle, draw", content)
        self.assertIn("\\draw[-, draw=black", content)
        self.assertIn("\\draw[->, draw=black", content)
        self.assertIn("$ e $", content)
        self.assertIn("$ f $", content)

    def test_drawing_export_tikz_is_restricted_to_owner(self):
        self.login()

        response = self.client.get(reverse("drawing_export_tikz", kwargs={"pk": self.other_drawing.pk}))

        self.assertEqual(response.status_code, 404)

    def test_drawing_detail_contains_tikz_export_link(self):
        self.login()

        response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("drawing_export_tikz", kwargs={"pk": self.drawing.pk}))
        self.assertContains(response, "Eksport")

    def test_drawing_detail_contains_latex_text_tool(self):
        self.login()

        response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "text.latex")
        self.assertContains(response, "\\alpha")

    def test_drawing_object_api_creates_latex_text_object(self):
        self.login()

        response = self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": self.drawing.pk}),
            data=json.dumps({
                "object_id": "txt1",
                "type": "text.latex",
                "data": {"x": 120, "y": 180, "text": "\\alpha+\\beta"},
                "style": {"fill": "#123456", "fontSize": 20, "showLabel": True},
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        obj = DrawingObject.objects.get(drawing=self.drawing, object_id="txt1")
        self.assertEqual(obj.type, "text.latex")
        self.assertEqual(obj.data["text"], "\\alpha+\\beta")
        self.assertEqual(obj.style["fontSize"], 20)

    def test_drawing_editor_static_js_contains_latex_text_support(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("isTextLike", source)
        self.assertIn("renderLatexText", source)
        self.assertIn("text.latex", source)
        self.assertIn("fontSize", source)

    def test_drawing_export_tikz_contains_latex_text_object(self):
        self.login()
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="txt1",
            type="text.latex",
            data={"x": 200, "y": 320, "text": "\\alpha+\\beta"},
            style={"fill": "#123456", "fontSize": 20, "showLabel": True},
        )

        response = self.client.get(reverse("drawing_export_tikz", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("\\definecolor{mde123456}{HTML}{123456}", content)
        self.assertIn("text=mde123456", content)
        self.assertIn("$ \\alpha+\\beta $", content)

    def test_drawing_export_tikz_skips_hidden_latex_text_object(self):
        self.login()
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="txt1",
            type="text.latex",
            data={"x": 200, "y": 320, "text": "hidden"},
            style={"fill": "#123456", "showLabel": False},
        )

        response = self.client.get(reverse("drawing_export_tikz", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertNotIn("hidden", content)

    def test_drawing_tikz_preview_returns_json_code(self):
        self.login()
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="A",
            type="geometry.point",
            data={"x": 100, "y": 120, "label": "A"},
        )

        response = self.client.get(reverse("drawing_tikz_preview", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["drawing_id"], self.drawing.pk)
        self.assertIn("\\begin{tikzpicture}", payload["tikz"])
        self.assertIn("\\coordinate (A)", payload["tikz"])

    def test_drawing_tikz_preview_is_restricted_to_owner(self):
        self.login()

        response = self.client.get(reverse("drawing_tikz_preview", kwargs={"pk": self.other_drawing.pk}))

        self.assertEqual(response.status_code, 404)

    def test_drawing_detail_contains_tikz_preview_controls(self):
        self.login()

        response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("drawing_tikz_preview", kwargs={"pk": self.drawing.pk}))
        self.assertContains(response, "data-role=\"tikz-preview\"")
        self.assertContains(response, "data-action=\"preview-tikz\"")
        self.assertContains(response, "data-action=\"copy-tikz\"")
        self.assertContains(response, "Pokaż TikZ")

    def test_drawing_editor_static_js_contains_tikz_preview_support(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("previewTikz", source)
        self.assertIn("copyTikzToClipboard", source)
        self.assertIn("navigator.clipboard", source)
        self.assertIn("tikzPreviewUrl", source)
        self.assertIn("document.querySelector(\"[data-action='preview-tikz']\")", source)
        self.assertIn("document.querySelector(\"[data-role='tikz-preview']\")", source)

    def test_drawing_editor_static_css_contains_tikz_preview_styles(self):
        css_path = finders.find("routes/drawing_editor.css")
        self.assertIsNotNone(css_path)
        with open(css_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("drawing-editor__tikz-preview", source)
        self.assertIn("drawing-editor__tikz-textarea", source)

    def test_drawing_object_api_updates_point_label(self):
        self.login()
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="A",
            type="geometry.point",
            data={"x": 100, "y": 120, "label": "old"},
        )

        response = self.client.patch(
            reverse("drawing_object_detail", kwargs={"drawing_id": self.drawing.pk, "object_id": "A"}),
            data=json.dumps({"data": {"x": 100, "y": 120, "label": "new"}}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        obj = DrawingObject.objects.get(drawing=self.drawing, object_id="A")
        self.assertEqual(obj.data["label"], "new")
        self.assertEqual(response.json()["object"]["data"]["label"], "new")

    def test_drawing_object_api_updates_latex_text_content(self):
        self.login()
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="txt1",
            type="text.latex",
            data={"x": 100, "y": 120, "text": "x"},
        )

        response = self.client.patch(
            reverse("drawing_object_detail", kwargs={"drawing_id": self.drawing.pk, "object_id": "txt1"}),
            data=json.dumps({"data": {"x": 100, "y": 120, "text": "\\alpha"}}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        obj = DrawingObject.objects.get(drawing=self.drawing, object_id="txt1")
        self.assertEqual(obj.data["text"], "\\alpha")

    def test_drawing_detail_contains_content_editor_controls(self):
        self.login()

        response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-role=\"content-panel\"")
        self.assertContains(response, "data-role=\"content-label\"")
        self.assertContains(response, "data-action=\"apply-content\"")
        self.assertContains(response, "Treść zaznaczonego obiektu")

    def test_drawing_editor_static_js_contains_content_editor_support(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("updateContentPanel", source)
        self.assertIn("applySelectedContent", source)
        self.assertIn("contentLabelInput", source)
        self.assertIn("data-action='apply-content'", source)
        self.assertIn("body: JSON.stringify({data: newData})", source)

    def test_drawing_editor_static_css_contains_content_editor_styles(self):
        css_path = finders.find("routes/drawing_editor.css")
        self.assertIsNotNone(css_path)
        with open(css_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("drawing-editor__content-panel", source)
        self.assertIn("drawing-editor__content-panel--disabled", source)

    def test_drawing_object_api_can_create_duplicate_without_object_id(self):
        self.login()
        original = DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="A",
            type="geometry.point",
            data={"x": 100, "y": 120, "label": "A"},
            style={"fill": "#111827", "stroke": "#111827"},
        )

        response = self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": self.drawing.pk}),
            data=json.dumps({
                "type": original.type,
                "data": {"x": 128, "y": 148, "label": "A"},
                "style": original.style,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertNotEqual(payload["object"]["object_id"], "A")
        self.assertEqual(payload["object"]["data"]["x"], 128)
        self.assertEqual(payload["object"]["data"]["y"], 148)
        self.assertEqual(DrawingObject.objects.filter(drawing=self.drawing).count(), 2)

    def test_drawing_detail_contains_duplicate_button(self):
        self.login()

        response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-action=\"duplicate-selected\"")
        self.assertContains(response, "Duplikuj zaznaczone")

    def test_drawing_editor_static_js_contains_duplicate_support(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("duplicateSelectedObject", source)
        self.assertIn("duplicatePayloadForObject", source)
        self.assertIn("data-action='duplicate-selected'", source)
        self.assertIn("x + 28", source)
        self.assertIn("method: \"POST\"", source)
        self.assertIn("this.objects.push(result.object)", source)

    def test_drawing_detail_contains_undo_redo_buttons(self):
        self.login()

        response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-action=\"undo\"")
        self.assertContains(response, "data-action=\"redo\"")
        self.assertContains(response, "Cofnij")
        self.assertContains(response, "Ponów")

    def test_drawing_editor_static_js_contains_undo_redo_support(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("undoStack", source)
        self.assertIn("redoStack", source)
        self.assertIn("pushHistory", source)
        self.assertIn("undoLastAction", source)
        self.assertIn("redoLastAction", source)
        self.assertIn("executeHistoryCommand", source)
        self.assertIn("kind: \"create\"", source)
        self.assertIn("kind: \"delete\"", source)
        self.assertIn("kind: \"update\"", source)

    def test_drawing_editor_static_js_undo_redo_uses_api_methods(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("restoreObject", source)
        self.assertIn("deleteObjectById", source)
        self.assertIn("applyObjectSnapshot", source)
        self.assertIn("method: \"POST\"", source)
        self.assertIn("method: \"DELETE\"", source)
        self.assertIn("method: \"PATCH\"", source)

    def test_drawing_editor_static_css_contains_undo_redo_styles(self):
        css_path = finders.find("routes/drawing_editor.css")
        self.assertIsNotNone(css_path)
        with open(css_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn('[data-action="undo"]', source)
        self.assertIn('[data-action="redo"]', source)
        self.assertIn("cursor: not-allowed", source)

    def test_drawing_detail_contains_multi_selection_controls(self):
        self.login()

        response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-role=\"selection-count\"")
        self.assertContains(response, "Zaznaczono: 0")
        self.assertContains(response, "Ctrl/Shift-klik")
        self.assertContains(response, "Usuń zaznaczone")

    def test_drawing_editor_static_js_contains_multi_selection_support(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("selectedObjectIds", source)
        self.assertIn("toggleSelection", source)
        self.assertIn("selectedObjects", source)
        self.assertIn("positionedSelectedObjects", source)
        self.assertIn("event.shiftKey || event.ctrlKey || event.metaKey", source)
        self.assertIn("data-role='selection-count'", source)

    def test_drawing_editor_static_js_contains_group_operations(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("bulk-create", source)
        self.assertIn("bulk-delete", source)
        self.assertIn("bulk-update", source)
        self.assertIn("objectIds", source)
        self.assertIn("Promise.all", source)

    def test_drawing_editor_static_css_contains_selection_counter_styles(self):
        css_path = finders.find("routes/drawing_editor.css")
        self.assertIsNotNone(css_path)
        with open(css_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("drawing-editor__selection-counter", source)
        self.assertIn("border-radius: 999px", source)


    def test_drawing_detail_contains_default_style_controls(self):
        self.login()

        response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-role=\"default-style-panel\"")
        self.assertContains(response, "data-role=\"default-style-stroke\"")
        self.assertContains(response, "data-role=\"default-style-fill\"")
        self.assertContains(response, "data-role=\"default-style-stroke-width\"")
        self.assertContains(response, "data-role=\"default-style-radius\"")
        self.assertContains(response, "Styl nowych obiektów")
        self.assertContains(response, "Zaznaczanie / przesuwanie")

    def test_drawing_editor_static_js_contains_canvas_selection_and_default_style_support(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("currentToolSelectsOnly", source)
        self.assertIn("styleForNewObject", source)
        self.assertIn("defaultStyleFromControls", source)
        self.assertIn("bindDefaultStyleEvents", source)
        self.assertIn("drawing-editor-default-style", source)
        self.assertIn("drawing-line-hit", source)
        self.assertIn("data-role='default-style-stroke'", source)
        self.assertIn("localStorage", source)

    def test_drawing_editor_static_css_contains_canvas_selection_and_default_style_styles(self):
        css_path = finders.find("routes/drawing_editor.css")
        self.assertIsNotNone(css_path)
        with open(css_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("drawing-editor__default-style-panel", source)
        self.assertIn("drawing-line-hit", source)
        self.assertIn("drawing-line--selected", source)
        self.assertIn("pointer-events: auto", source)

class DrawingEditorRectangleSelectionTests(TestCase):
    def test_drawing_editor_static_js_contains_rectangle_selection_support(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("handleCanvasPointerDown", source)
        self.assertIn("selectionBoxState", source)
        self.assertIn("finishSelectionBox", source)
        self.assertIn("objectIdsInsideSelectionBox", source)
        self.assertIn("boundsIntersectSelectionBox", source)
        self.assertIn("drawing-editor__selection-box", source)
        self.assertIn("this.ignoreNextCanvasClick = true", source)

    def test_drawing_editor_static_css_contains_rectangle_selection_styles(self):
        css_path = finders.find("routes/drawing_editor.css")
        self.assertIsNotNone(css_path)
        with open(css_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("drawing-editor__selection-box", source)
        self.assertIn("stroke-dasharray", source)
        self.assertIn("pointer-events: none", source)

@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DrawingSettingsAndSnapTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice_settings", password="password123")
        self.other_user = User.objects.create_user(username="bob_settings", password="password123")
        self.drawing = Drawing.objects.create(
            user=self.user,
            title="Settings drawing",
            mode=Drawing.MODE_GEOMETRY,
        )
        self.other_drawing = Drawing.objects.create(
            user=self.other_user,
            title="Foreign settings drawing",
            mode=Drawing.MODE_GEOMETRY,
        )

    def login(self):
        self.client.login(username="alice_settings", password="password123")

    def test_drawing_has_settings_json_field(self):
        self.assertEqual(self.drawing.settings, {})
        self.drawing.settings = {
            "canvas": {"width": 1000, "height": 600, "gridSize": 25, "showGrid": True, "snapToGrid": True},
            "tikz": {"scale": 50},
        }
        self.drawing.save()
        self.drawing.refresh_from_db()
        self.assertTrue(self.drawing.settings["canvas"]["snapToGrid"])
        self.assertEqual(self.drawing.settings["tikz"]["scale"], 50)

    def test_drawing_settings_api_gets_and_updates_settings(self):
        self.login()

        get_response = self.client.get(reverse("drawing_settings_api", kwargs={"pk": self.drawing.pk}))
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["settings"]["canvas"]["width"], 900)
        self.assertFalse(get_response.json()["settings"]["canvas"]["snapToGrid"])

        patch_response = self.client.patch(
            reverse("drawing_settings_api", kwargs={"pk": self.drawing.pk}),
            data=json.dumps({
                "settings": {
                    "canvas": {
                        "width": 1000,
                        "height": 640,
                        "gridSize": 25,
                        "showGrid": False,
                        "snapToGrid": True,
                    },
                    "tikz": {"scale": 50},
                }
            }),
            content_type="application/json",
        )

        self.assertEqual(patch_response.status_code, 200)
        self.drawing.refresh_from_db()
        self.assertEqual(self.drawing.settings["canvas"]["width"], 1000)
        self.assertEqual(self.drawing.settings["canvas"]["gridSize"], 25)
        self.assertTrue(self.drawing.settings["canvas"]["snapToGrid"])
        self.assertEqual(self.drawing.settings["tikz"]["scale"], 50)

    def test_drawing_settings_api_is_restricted_to_owner(self):
        self.login()

        response = self.client.get(reverse("drawing_settings_api", kwargs={"pk": self.other_drawing.pk}))

        self.assertEqual(response.status_code, 404)

    def test_drawing_detail_contains_settings_controls(self):
        self.login()

        response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("drawing_settings_api", kwargs={"pk": self.drawing.pk}))
        self.assertContains(response, "data-role=\"settings-panel\"")
        self.assertContains(response, "data-role=\"settings-grid-size\"")
        self.assertContains(response, "data-role=\"settings-snap-to-grid\"")
        self.assertContains(response, "Przyciągaj punkty do siatki")

    def test_drawing_export_tikz_uses_drawing_settings_scale_and_height(self):
        self.login()
        self.drawing.settings = {
            "canvas": {"width": 1000, "height": 600, "gridSize": 50, "showGrid": True, "snapToGrid": False},
            "tikz": {"scale": 50},
        }
        self.drawing.save()
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="A",
            type="geometry.point",
            data={"x": 100, "y": 100, "label": "A"},
        )

        response = self.client.get(reverse("drawing_export_tikz", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("\\coordinate (A) at (2, 10);", content)

    def test_drawing_editor_static_js_contains_settings_and_snap_support(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("settingsUrl", source)
        self.assertIn("applyDrawingSettings", source)
        self.assertIn("snapPoint", source)
        self.assertIn("settings-snap-to-grid", source)
        self.assertIn("renderGrid", source)
        self.assertIn('method: "PATCH"', source)

    def test_drawing_editor_static_css_contains_settings_panel_styles(self):
        css_path = finders.find("routes/drawing_editor.css")
        self.assertIsNotNone(css_path)
        with open(css_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("drawing-editor__settings-panel", source)
        self.assertIn("pointer-events: none", source)

@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DrawingCircleObjectTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice_circle", password="password123")
        self.drawing = Drawing.objects.create(
            user=self.user,
            title="Circle drawing",
            mode=Drawing.MODE_GEOMETRY,
        )

    def login(self):
        self.client.login(username="alice_circle", password="password123")

    def test_api_can_store_geometry_circle_dependent_on_two_points(self):
        self.login()
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="A",
            type="geometry.point",
            data={"x": 100, "y": 100, "label": "A"},
        )
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="B",
            type="geometry.point",
            data={"x": 200, "y": 100, "label": "B"},
        )

        response = self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": self.drawing.pk}),
            data=json.dumps({
                "object_id": "circle_c",
                "type": "geometry.circle",
                "data": {"center": "A", "point": "B", "label": "c"},
                "style": {"stroke": "#ff0000", "fill": "none", "strokeWidth": 2},
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        obj = DrawingObject.objects.get(drawing=self.drawing, object_id="circle_c")
        self.assertEqual(obj.type, "geometry.circle")
        self.assertEqual(obj.data["center"], "A")
        self.assertEqual(obj.data["point"], "B")

    def test_drawing_detail_contains_geometry_circle_tool(self):
        self.login()

        response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "geometry.circle")

    def test_drawing_editor_static_js_contains_circle_support(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("isCircleLike", source)
        self.assertIn("currentToolCreatesCircle", source)
        self.assertIn("renderCircle", source)
        self.assertIn("center: startId", source)
        self.assertIn("point: endId", source)
        self.assertIn("drawing-circle-hit", source)

    def test_drawing_export_tikz_exports_geometry_circle(self):
        self.login()
        self.drawing.settings = {
            "canvas": {"width": 900, "height": 520, "gridSize": 50, "showGrid": True, "snapToGrid": False},
            "tikz": {"scale": 100},
        }
        self.drawing.save()
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="A",
            type="geometry.point",
            data={"x": 100, "y": 100, "label": "A"},
        )
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="B",
            type="geometry.point",
            data={"x": 200, "y": 100, "label": "B"},
        )
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="circle_c",
            type="geometry.circle",
            data={"center": "A", "point": "B", "label": "c"},
            style={"stroke": "#ff0000", "fill": "none", "strokeWidth": 2},
        )

        response = self.client.get(reverse("drawing_export_tikz", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("\\definecolor{mdeFF0000}{HTML}{FF0000}", content)
        self.assertIn("\\draw[draw=mdeFF0000, line width=2pt] (1, 4.2) circle (1cm);", content)
        self.assertIn("\\node[right] at (2, 4.2) {$ c $};", content)

@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DrawingPolygonObjectTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice_polygon", password="password123")
        self.drawing = Drawing.objects.create(
            user=self.user,
            title="Polygon drawing",
            mode=Drawing.MODE_GEOMETRY,
        )

    def login(self):
        self.client.login(username="alice_polygon", password="password123")

    def create_triangle_points(self):
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="A",
            type="geometry.point",
            data={"x": 100, "y": 100, "label": "A"},
        )
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="B",
            type="geometry.point",
            data={"x": 200, "y": 100, "label": "B"},
        )
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="C",
            type="geometry.point",
            data={"x": 150, "y": 200, "label": "C"},
        )

    def test_api_can_store_geometry_polygon_dependent_on_points(self):
        self.login()
        self.create_triangle_points()

        response = self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": self.drawing.pk}),
            data=json.dumps({
                "object_id": "triangle_abc",
                "type": "geometry.polygon",
                "data": {"points": ["A", "B", "C"], "closed": True, "label": "T"},
                "style": {"stroke": "#00aa00", "fill": "#ffffff", "strokeWidth": 2},
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        obj = DrawingObject.objects.get(drawing=self.drawing, object_id="triangle_abc")
        self.assertEqual(obj.type, "geometry.polygon")
        self.assertEqual(obj.data["points"], ["A", "B", "C"])
        self.assertTrue(obj.data["closed"])

    def test_drawing_detail_contains_geometry_polygon_tool_without_finish_buttons(self):
        self.login()

        response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "geometry.polygon")
        self.assertContains(response, "Wielokąt domykasz kliknięciem pierwszego punktu")
        self.assertNotContains(response, 'data-action="finish-polygon"')
        self.assertNotContains(response, 'data-action="cancel-polygon"')

    def test_drawing_editor_static_js_contains_polygon_support(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("isPolygonLike", source)
        self.assertIn("currentToolCreatesPolygon", source)
        self.assertIn("pendingPolygonPointIds", source)
        self.assertIn("finishPendingPolygon", source)
        self.assertIn("renderPolygon", source)
        self.assertIn("drawing-polygon-hit", source)

    def test_drawing_export_tikz_exports_geometry_polygon(self):
        self.login()
        self.drawing.settings = {
            "canvas": {"width": 900, "height": 520, "gridSize": 50, "showGrid": True, "snapToGrid": False},
            "tikz": {"scale": 100},
        }
        self.drawing.save()
        self.create_triangle_points()
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="triangle_abc",
            type="geometry.polygon",
            data={"points": ["A", "B", "C"], "closed": True, "label": "T"},
            style={"stroke": "#00aa00", "fill": "none", "strokeWidth": 2},
        )

        response = self.client.get(reverse("drawing_export_tikz", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("\\definecolor{mde00AA00}{HTML}{00AA00}", content)
        self.assertIn("\\draw[draw=mde00AA00, line width=2pt] (A) -- (B) -- (C) -- cycle;", content)
        self.assertIn("\\node at", content)
        self.assertIn("$ T $", content)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DrawingObjectTypeSeparationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="type_rules_user", password="password123")
        self.drawing = Drawing.objects.create(user=self.user, title="Type rules", mode=Drawing.MODE_MIXED)
        self.client.login(username="type_rules_user", password="password123")
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="gp",
            type="geometry.point",
            data={"x": 100, "y": 100},
        )
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="gv",
            type="graph.vertex",
            data={"x": 200, "y": 100},
        )

    def post_object(self, payload):
        return self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": self.drawing.pk}),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_geometry_circle_rejects_graph_vertex_as_reference(self):
        response = self.post_object({
            "type": "geometry.circle",
            "data": {"center": "gp", "point": "gv"},
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("point", response.json()["errors"])

    def test_geometry_polygon_rejects_graph_vertex_as_point(self):
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="gp2",
            type="geometry.point",
            data={"x": 150, "y": 180},
        )

        response = self.post_object({
            "type": "geometry.polygon",
            "data": {"points": ["gp", "gp2", "gv"], "closed": True},
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("points[2]", response.json()["errors"])

    def test_graph_edge_rejects_geometry_point_as_endpoint(self):
        response = self.post_object({
            "type": "graph.edge",
            "data": {"source": "gv", "target": "gp"},
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("target", response.json()["errors"])

    def test_frontend_contains_automatic_circle_and_polygon_point_creation(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("createGeometryPointAt", source)
        self.assertIn("pointIsAllowedForCurrentTool", source)
        self.assertIn("Wierzchołki grafu nie są używane w geometrii", source)
        self.assertIn("Kliknij ponownie pierwszy punkt", source)



    def test_frontend_contains_step21_segment_autocreate_and_graph_edge_tools(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("graph.edge.undirected", source)
        self.assertIn("graph.edge.directed", source)
        self.assertIn("Utworzono pierwszy koniec odcinka", source)
        self.assertIn("styleDirectedInput", source)

    def test_tikz_export_undirected_graph_edge_uses_plain_line(self):
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="v1",
            type="graph.vertex",
            data={"x": 100, "y": 100, "label": "v_1"},
        )
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="v2",
            type="graph.vertex",
            data={"x": 200, "y": 100, "label": "v_2"},
        )
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="e",
            type="graph.edge",
            data={"source": "v1", "target": "v2"},
            style={"directed": False},
        )

        response = self.client.get(reverse("drawing_export_tikz", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("\\draw[-, draw=black", content)
        self.assertNotIn("\\draw[->, draw=black", content)



@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class MainNavigationCleanupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="navuser", password="password123")

    def login(self):
        self.client.login(username="navuser", password="password123")

    def test_home_page_is_drawing_list(self):
        self.login()

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Moje rysunki")
        self.assertNotContains(response, "My routes")
        self.assertNotContains(response, "New route")

    def test_main_navigation_shows_only_drawing_links(self):
        self.login()

        response = self.client.get(reverse("drawing_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Route Editor")
        self.assertContains(response, "Moje rysunki")
        self.assertContains(response, "Nowy rysunek")
        self.assertNotContains(response, "My routes")
        self.assertNotContains(response, "New route")
        self.assertNotContains(response, "Structured drawings")

    def test_legacy_route_editor_still_has_urls_but_is_hidden_from_menu(self):
        self.login()

        response = self.client.get(reverse("route_list"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("/legacy/routes/", reverse("route_list"))
        self.assertNotContains(response, "New route")
        self.assertNotContains(response, "My routes")

@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DrawingToolboxUiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="toolbox_user", password="password123")
        self.drawing = Drawing.objects.create(user=self.user, title="Toolbox drawing", mode=Drawing.MODE_MIXED)
        self.client.login(username="toolbox_user", password="password123")

    def test_drawing_detail_contains_grouped_toolbox(self):
        response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="drawing-editor__toolbox"')
        self.assertContains(response, 'data-tool-group="selection"')
        self.assertContains(response, 'data-tool-group="text"')
        self.assertContains(response, 'data-tool-group="graph"')
        self.assertContains(response, 'data-tool-group="geometry"')
        self.assertContains(response, 'data-tool-button="select"')
        self.assertContains(response, 'data-tool-button="graph.vertex"')
        self.assertContains(response, 'data-tool-button="graph.edge.undirected"')
        self.assertContains(response, 'data-tool-button="graph.edge.directed"')
        self.assertContains(response, 'data-tool-button="geometry.circle"')
        self.assertContains(response, 'data-tool-button="geometry.polygon"')

    def test_hidden_select_still_exists_as_tool_state_for_frontend(self):
        response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-role="object-type"')
        self.assertContains(response, 'class="drawing-editor__tool-select"')

    def test_drawing_editor_js_syncs_tool_buttons_with_current_tool(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("toolButtons", source)
        self.assertIn("setToolType", source)
        self.assertIn("syncToolButtons", source)
        self.assertIn("drawing-editor__tool-button--active", source)
        self.assertIn("aria-pressed", source)

    def test_drawing_editor_css_contains_grouped_toolbox_styles(self):
        css_path = finders.find("routes/drawing_editor.css")
        self.assertIsNotNone(css_path)
        with open(css_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("drawing-editor__toolbox", source)
        self.assertIn("drawing-editor__tool-group", source)
        self.assertIn("drawing-editor__tool-button", source)
        self.assertIn("drawing-editor__tool-button--active", source)

@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DrawingObjectOrderingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="order_user", password="password123")
        self.drawing = Drawing.objects.create(user=self.user, title="Ordering", mode=Drawing.MODE_MIXED)
        self.client.login(username="order_user", password="password123")
        self.back = DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="back",
            type="geometry.point",
            data={"x": 100, "y": 100, "label": "B"},
            order=0,
        )
        self.front = DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="front",
            type="geometry.point",
            data={"x": 200, "y": 100, "label": "F"},
            order=10,
        )

    def test_objects_api_returns_objects_ordered_by_order(self):
        response = self.client.get(reverse("drawing_objects_collection", kwargs={"drawing_id": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        object_ids = [item["object_id"] for item in response.json()["objects"]]
        self.assertEqual(object_ids, ["back", "front"])

    def test_object_order_can_be_updated_with_patch(self):
        response = self.client.patch(
            reverse("drawing_object_detail", kwargs={"drawing_id": self.drawing.pk, "object_id": "back"}),
            data=json.dumps({"order": 20}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.back.refresh_from_db()
        self.assertEqual(self.back.order, 20)

    def test_drawing_detail_contains_ordering_buttons(self):
        response = self.client.get(reverse("drawing_detail", kwargs={"pk": self.drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-action="bring-to-front"')
        self.assertContains(response, 'data-action="send-to-back"')
        self.assertContains(response, 'data-action="move-up"')
        self.assertContains(response, 'data-action="move-down"')
        self.assertContains(response, "Na wierzch")
        self.assertContains(response, "Pod spód")

    def test_drawing_editor_js_contains_reordering_logic(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        with open(js_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("reorderSelectedObjects", source)
        self.assertIn("sortedObjects", source)
        self.assertIn("bring-to-front", source)
        self.assertIn("send-to-back", source)
        self.assertIn("move-up", source)
        self.assertIn("move-down", source)
        self.assertIn("JSON.stringify({order: object.order})", source)

    def test_drawing_editor_css_contains_order_label_style(self):
        css_path = finders.find("routes/drawing_editor.css")
        self.assertIsNotNone(css_path)
        with open(css_path, encoding="utf-8") as file:
            source = file.read()

        self.assertIn("drawing-editor__object-row em", source)

class DrawingDependentGeometryPointMovementTests(TestCase):
    def test_drawing_editor_js_renders_dependent_shapes_before_control_points(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        content = Path(js_path).read_text(encoding="utf-8")
        self.assertIn('sortedObjectsForRendering', content)
        self.assertIn('renderingLayer(object)', content)
        self.assertIn('isPolygonLike(object) || isCircleLike(object) || isLineLike(object)', content)
        self.assertIn('isPointLike(object) || isTextLike(object)', content)

    def test_drawing_editor_switches_to_select_after_geometry_creation(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        content = Path(js_path).read_text(encoding="utf-8")
        self.assertIn('switchToSelectAfterGeometryCreation', content)
        self.assertIn('this.setToolType("select")', content)
        self.assertIn('Możesz teraz przesuwać jego punkty sterujące', content)

@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DrawingModeToolAvailabilityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="mode_user", password="password123")
        self.client.login(username="mode_user", password="password123")

    def create_drawing(self, mode):
        return Drawing.objects.create(user=self.user, title=f"Drawing {mode}", mode=mode)

    def test_create_drawing_form_explains_modes(self):
        response = self.client.get(reverse("drawing_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tryb rysunku")
        self.assertContains(response, "Graf")
        self.assertContains(response, "Geometria")
        self.assertContains(response, "Wykresy")
        self.assertNotContains(response, "Wszystko")


    def test_create_drawing_form_rejects_mixed_mode(self):
        response = self.client.post(reverse("drawing_create"), {"title": "No mixed", "mode": Drawing.MODE_MIXED})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Drawing.objects.filter(user=self.user, title="No mixed").exists())
        self.assertFormError(response.context["form"], "mode", "Select a valid choice. mixed is not one of the available choices.")

    def test_graph_mode_shows_only_graph_tools(self):
        drawing = self.create_drawing(Drawing.MODE_GRAPH)
        response = self.client.get(reverse("drawing_detail", kwargs={"pk": drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-drawing-mode="graph"')
        self.assertContains(response, 'data-tool-group="graph"')
        self.assertContains(response, 'data-tool-button="graph.vertex"')
        self.assertContains(response, 'data-tool-button="graph.edge.undirected"')
        self.assertNotContains(response, 'data-tool-group="geometry"')
        self.assertNotContains(response, 'data-tool-button="geometry.circle"')
        self.assertNotContains(response, 'data-tool-group="text"')

    def test_geometry_mode_shows_only_geometry_tools(self):
        drawing = self.create_drawing(Drawing.MODE_GEOMETRY)
        response = self.client.get(reverse("drawing_detail", kwargs={"pk": drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-drawing-mode="geometry"')
        self.assertContains(response, 'data-tool-group="geometry"')
        self.assertContains(response, 'data-tool-button="geometry.circle"')
        self.assertNotContains(response, 'data-tool-group="graph"')
        self.assertNotContains(response, 'data-tool-button="graph.vertex"')
        self.assertNotContains(response, 'data-tool-group="text"')

    def test_plot_mode_shows_plot_tools_without_graph_or_geometry_tools(self):
        drawing = self.create_drawing(Drawing.MODE_PLOT)
        response = self.client.get(reverse("drawing_detail", kwargs={"pk": drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-drawing-mode="plot"')
        self.assertContains(response, 'data-tool-group="plot"')
        self.assertContains(response, 'data-tool-button="plot.series"')
        self.assertContains(response, 'data-role="plot-panel"')
        self.assertContains(response, "Wykres z danych")
        self.assertNotContains(response, 'data-tool-group="graph"')
        self.assertNotContains(response, 'data-tool-group="geometry"')

    def test_mixed_mode_shows_graph_geometry_and_text_tools(self):
        drawing = self.create_drawing(Drawing.MODE_MIXED)
        response = self.client.get(reverse("drawing_detail", kwargs={"pk": drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-tool-group="graph"')
        self.assertContains(response, 'data-tool-group="geometry"')
        self.assertContains(response, 'data-tool-group="text"')

    def test_graph_mode_api_rejects_geometry_object(self):
        drawing = self.create_drawing(Drawing.MODE_GRAPH)
        response = self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": drawing.pk}),
            data=json.dumps({
                "object_id": "p1",
                "type": "geometry.point",
                "data": {"x": 10, "y": 10},
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("type", response.json()["errors"])

    def test_geometry_mode_api_rejects_graph_object(self):
        drawing = self.create_drawing(Drawing.MODE_GEOMETRY)
        response = self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": drawing.pk}),
            data=json.dumps({
                "object_id": "v1",
                "type": "graph.vertex",
                "data": {"x": 10, "y": 10},
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("type", response.json()["errors"])

    def test_mixed_mode_api_allows_text_object(self):
        drawing = self.create_drawing(Drawing.MODE_MIXED)
        response = self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": drawing.pk}),
            data=json.dumps({
                "object_id": "t1",
                "type": "text.latex",
                "data": {"x": 10, "y": 10, "text": "x_i"},
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)

    def test_plot_mode_api_rejects_graph_objects(self):
        drawing = self.create_drawing(Drawing.MODE_PLOT)
        response = self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": drawing.pk}),
            data=json.dumps({
                "object_id": "v1",
                "type": "graph.vertex",
                "data": {"x": 10, "y": 10},
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("not allowed", response.json()["errors"]["type"])

    def test_plot_mode_api_allows_plot_series(self):
        drawing = self.create_drawing(Drawing.MODE_PLOT)
        response = self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": drawing.pk}),
            data=json.dumps({
                "object_id": "series1",
                "type": "plot.series",
                "data": {
                    "points": [[0, 0], [1, 2], [2, 3]],
                    "label": "Dane",
                    "plotType": "line_markers",
                },
                "style": {"stroke": "#2563eb", "strokeWidth": 2},
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["object"]["type"], "plot.series")

    def test_plot_series_requires_numeric_points(self):
        drawing = self.create_drawing(Drawing.MODE_PLOT)
        response = self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": drawing.pk}),
            data=json.dumps({
                "object_id": "bad_series",
                "type": "plot.series",
                "data": {"points": [[0, "x"]]},
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("points[0]", response.json()["errors"])

    def test_plot_series_exports_to_pgfplots(self):
        drawing = self.create_drawing(Drawing.MODE_PLOT)
        DrawingObject.objects.create(
            drawing=drawing,
            object_id="series1",
            type="plot.series",
            data={"points": [[0, 0], [1, 2]], "label": "Dane", "plotType": "line"},
            style={"stroke": "#2563eb", "strokeWidth": 2},
        )
        response = self.client.get(reverse("drawing_export_tikz", kwargs={"pk": drawing.pk}))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("\\begin{axis}", content)
        self.assertIn("\\addplot+", content)
        self.assertIn("(0, 0)", content)
        self.assertIn("\\addlegendentry", content)

    def test_drawing_editor_js_reads_drawing_mode_and_rejects_unavailable_tools(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        content = Path(js_path).read_text(encoding="utf-8")

        self.assertIn("drawingMode", content)
        self.assertIn("availableToolTypes", content)
        self.assertIn("To narzędzie nie jest dostępne", content)

    def test_plot_panel_contains_axis_settings(self):
        drawing = self.create_drawing(Drawing.MODE_PLOT)
        response = self.client.get(reverse("drawing_detail", kwargs={"pk": drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-role="plot-axis-settings"')
        self.assertContains(response, 'data-role="plot-title"')
        self.assertContains(response, 'data-role="plot-x-label"')
        self.assertContains(response, 'data-role="plot-y-label"')
        self.assertContains(response, 'data-role="plot-x-min"')
        self.assertContains(response, 'data-role="plot-y-max"')

    def test_plot_series_accepts_axis_settings(self):
        drawing = self.create_drawing(Drawing.MODE_PLOT)
        response = self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": drawing.pk}),
            data=json.dumps({
                "object_id": "series_axis",
                "type": "plot.series",
                "data": {
                    "points": [[0, 0], [1, 2]],
                    "plotType": "line",
                    "axis": {
                        "title": "Tytuł",
                        "xLabel": "t",
                        "yLabel": "f(t)",
                        "xMin": 0,
                        "xMax": 10,
                        "yMin": -1,
                        "yMax": 5,
                    },
                },
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        axis = response.json()["object"]["data"]["axis"]
        self.assertEqual(axis["title"], "Tytuł")
        self.assertEqual(axis["xMax"], 10)

    def test_plot_series_rejects_invalid_axis_range(self):
        drawing = self.create_drawing(Drawing.MODE_PLOT)
        response = self.client.post(
            reverse("drawing_objects_collection", kwargs={"drawing_id": drawing.pk}),
            data=json.dumps({
                "object_id": "bad_axis",
                "type": "plot.series",
                "data": {
                    "points": [[0, 0], [1, 2]],
                    "axis": {"xMin": 5, "xMax": 5},
                },
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("axis.xRange", response.json()["errors"])

    def test_plot_series_axis_settings_export_to_pgfplots(self):
        drawing = self.create_drawing(Drawing.MODE_PLOT)
        DrawingObject.objects.create(
            drawing=drawing,
            object_id="series_axis",
            type="plot.series",
            data={
                "points": [[0, 0], [1, 2]],
                "label": "Dane",
                "plotType": "line",
                "axis": {
                    "title": "Wyniki",
                    "xLabel": "t",
                    "yLabel": "f(t)",
                    "xMin": 0,
                    "xMax": 10,
                    "yMin": -1,
                    "yMax": 5,
                },
            },
            style={"stroke": "#2563eb", "strokeWidth": 2},
        )
        response = self.client.get(reverse("drawing_export_tikz", kwargs={"pk": drawing.pk}))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("title={$Wyniki$}", content)
        self.assertIn("xlabel={$t$}", content)
        self.assertIn("ylabel={$f(t)$}", content)
        self.assertIn("xmin=0", content)
        self.assertIn("xmax=10", content)
        self.assertIn("ymin=-1", content)
        self.assertIn("ymax=5", content)

    def test_drawing_editor_js_contains_plot_axis_support(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        content = Path(js_path).read_text(encoding="utf-8")

        self.assertIn("plotAxisSettingsFromPanel", content)
        self.assertIn("plotTitleInput", content)
        self.assertIn("xMin", content)
        self.assertIn("yMax", content)

class PlotPanelUxStep27Tests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="plot_ux_user", password="password123")
        self.client.login(username="plot_ux_user", password="password123")

    def create_drawing(self, mode=Drawing.MODE_PLOT):
        return Drawing.objects.create(user=self.user, title=f"Drawing {mode}", mode=mode)

    def test_plot_data_panel_is_below_canvas_not_in_side_panel(self):
        drawing = self.create_drawing(Drawing.MODE_PLOT)
        response = self.client.get(reverse("drawing_detail", kwargs={"pk": drawing.pk}))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn('drawing-editor__plot-panel--below-canvas', content)
        self.assertIn('Zastosuj dane wykresu', content)
        self.assertLess(content.index('data-role="drawing-status"'), content.index('data-role="plot-panel"'))
        self.assertLess(content.index('data-role="plot-panel"'), content.index('class="drawing-editor__side-panel"'))

    def test_plot_panel_explains_empty_data_removes_plot(self):
        drawing = self.create_drawing(Drawing.MODE_PLOT)
        response = self.client.get(reverse("drawing_detail", kwargs={"pk": drawing.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Jeśli pole danych będzie puste')
        self.assertContains(response, 'istniejący wykres zostanie usunięty')

    def test_drawing_editor_js_syncs_plot_series_from_textarea(self):
        js_path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(js_path)
        content = Path(js_path).read_text(encoding="utf-8")

        self.assertIn('parsePlotData(this.plotDataInput ? this.plotDataInput.value : "", {allowEmpty: true})', content)
        self.assertIn('deletePlotSeriesObjects', content)
        self.assertIn('updatePlotPanelFromSelection', content)
        self.assertIn('Na rysunku są tylko punkty wpisane w polu danych', content)

class PlotChartStep29Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="plot_chart_user", password="password123")

    def setUp(self):
        self.client.login(username="plot_chart_user", password="password123")
        self.drawing = Drawing.objects.create(user=self.user, title="Chart", mode=Drawing.MODE_PLOT)

    def test_plot_mode_allows_plot_chart_object(self):
        response = self.client.post(
            reverse("drawing_objects_collection", args=[self.drawing.id]),
            data=json.dumps({
                "type": "plot.chart",
                "data": {
                    "axis": {"title": "Wyniki", "xLabel": "x", "yLabel": "y"},
                    "legend": {"show": True},
                    "series": [
                        {"label": "A", "plotType": "line", "points": [[0, 0], [1, 2]], "style": {"stroke": "#2563eb"}},
                        {"label": "B", "plotType": "scatter", "points": [[0, 1], [1, 3]], "style": {"stroke": "#dc2626"}},
                    ],
                    "functions": [
                        {"expression": "x^2", "domainMin": -2, "domainMax": 2, "label": "x^2", "color": "#16a34a"}
                    ],
                },
                "style": {"stroke": "#2563eb", "strokeWidth": 2},
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["object"]["type"], "plot.chart")

    def test_plot_chart_rejects_invalid_series_point(self):
        response = self.client.post(
            reverse("drawing_objects_collection", args=[self.drawing.id]),
            data=json.dumps({
                "type": "plot.chart",
                "data": {
                    "series": [{"label": "A", "plotType": "line", "points": [[0, "bad"]]}],
                    "functions": [],
                },
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("series[0].points[0]", response.json()["errors"])

    def test_plot_chart_exports_multiple_series_and_function(self):
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="chart1",
            type="plot.chart",
            data={
                "axis": {"title": "Wyniki", "xLabel": "t", "yLabel": "f(t)"},
                "legend": {"show": True},
                "series": [
                    {"label": "A", "plotType": "line", "points": [[0, 0], [1, 2]], "style": {"stroke": "#2563eb"}},
                    {"label": "B", "plotType": "scatter", "points": [[0, 1], [1, 3]], "style": {"stroke": "#dc2626"}},
                ],
                "functions": [
                    {"expression": "x^2", "domainMin": -2, "domainMax": 2, "label": "x^2", "color": "#16a34a"}
                ],
            },
            style={"strokeWidth": 2},
        )
        response = self.client.get(reverse("drawing_export_tikz", args=[self.drawing.id]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("\\begin{axis}", content)
        self.assertIn("\\addplot+", content)
        self.assertIn("coordinates", content)
        self.assertIn("domain=-2:2", content)
        self.assertIn("{x^2}", content)
        self.assertIn("\\addlegendentry{$ A $}", content)
        self.assertIn("\\addlegendentry{$ B $}", content)

    def test_plot_panel_contains_multiple_series_and_function_controls(self):
        response = self.client.get(reverse("drawing_detail", args=[self.drawing.id]))
        self.assertContains(response, "plot.chart")
        self.assertContains(response, "Serie danych")
        self.assertContains(response, "Funkcje")
        self.assertContains(response, 'data-role="plot-functions"')
        self.assertContains(response, 'data-role="plot-show-legend"')

class DrawingJsonImportExportStep30Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="json_user", password="password123")
        cls.other_user = User.objects.create_user(username="json_other", password="password123")

    def setUp(self):
        self.client.login(username="json_user", password="password123")

    def test_export_drawing_json_contains_structural_document(self):
        drawing = Drawing.objects.create(
            user=self.user,
            title="Geo JSON",
            mode=Drawing.MODE_GEOMETRY,
            settings={"canvas": {"width": 900, "height": 520, "gridSize": 25, "showGrid": True, "snapToGrid": True}},
        )
        DrawingObject.objects.create(
            drawing=drawing,
            object_id="A",
            type="geometry.point",
            data={"x": 100, "y": 200, "label": "A"},
            style={"stroke": "#111827", "fill": "#ffffff"},
            order=2,
        )

        response = self.client.get(reverse("drawing_export_json", args=[drawing.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json; charset=utf-8")
        self.assertIn("attachment", response["Content-Disposition"])
        document = json.loads(response.content.decode("utf-8"))
        self.assertEqual(document["title"], "Geo JSON")
        self.assertEqual(document["mode"], Drawing.MODE_GEOMETRY)
        self.assertEqual(document["settings"]["canvas"]["gridSize"], 25)
        self.assertEqual(document["objects"][0]["object_id"], "A")
        self.assertEqual(document["objects"][0]["type"], "geometry.point")

    def test_export_drawing_json_rejects_other_users_drawing(self):
        drawing = Drawing.objects.create(user=self.other_user, title="Secret", mode=Drawing.MODE_GRAPH)
        response = self.client.get(reverse("drawing_export_json", args=[drawing.id]))
        self.assertEqual(response.status_code, 404)

    def test_import_drawing_json_creates_new_drawing_and_objects(self):
        document = {
            "schema_version": 1,
            "title": "Imported geometry",
            "mode": "geometry",
            "settings": {"canvas": {"width": 800, "height": 500, "gridSize": 20, "showGrid": True, "snapToGrid": False}},
            "metadata": {"source": "test"},
            "objects": [
                {"object_id": "A", "type": "geometry.point", "data": {"x": 10, "y": 20, "label": "A"}, "style": {"stroke": "#111827"}, "order": 0},
                {"object_id": "B", "type": "geometry.point", "data": {"x": 60, "y": 20, "label": "B"}, "style": {"stroke": "#111827"}, "order": 1},
                {"object_id": "AB", "type": "geometry.segment", "data": {"source": "A", "target": "B", "label": "a"}, "style": {"stroke": "#2563eb"}, "order": 2},
            ],
        }
        upload = SimpleUploadedFile("drawing.json", json.dumps(document).encode("utf-8"), content_type="application/json")

        response = self.client.post(reverse("drawing_import_json"), {"json_file": upload})

        self.assertEqual(response.status_code, 302)
        imported = Drawing.objects.get(user=self.user, title="Imported geometry")
        self.assertEqual(imported.mode, Drawing.MODE_GEOMETRY)
        self.assertEqual(imported.drawing_objects.count(), 3)
        self.assertTrue(imported.metadata["imported_from_json"])
        self.assertTrue(imported.drawing_objects.filter(object_id="AB", type="geometry.segment").exists())

    def test_import_drawing_json_rejects_invalid_mode(self):
        document = {"title": "Bad", "mode": "mixed", "objects": []}
        response = self.client.post(reverse("drawing_import_json"), {"json_text": json.dumps(document)})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "mode", status_code=400)
        self.assertFalse(Drawing.objects.filter(user=self.user, title="Bad").exists())

    def test_import_drawing_json_rejects_geometry_reference_to_graph_vertex(self):
        document = {
            "title": "Bad refs",
            "mode": "geometry",
            "objects": [
                {"object_id": "v1", "type": "graph.vertex", "data": {"x": 10, "y": 20}, "style": {}, "order": 0},
                {"object_id": "c1", "type": "geometry.circle", "data": {"center": "v1", "point": "v1"}, "style": {}, "order": 1},
            ],
        }
        response = self.client.post(reverse("drawing_import_json"), {"json_text": json.dumps(document)})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Drawing.objects.filter(user=self.user, title="Bad refs").exists())

    def test_drawing_list_and_detail_link_json_import_export(self):
        drawing = Drawing.objects.create(user=self.user, title="Links", mode=Drawing.MODE_GRAPH)
        list_response = self.client.get(reverse("drawing_list"))
        detail_response = self.client.get(reverse("drawing_detail", args=[drawing.id]))

        self.assertContains(list_response, reverse("drawing_import_json"))
        self.assertContains(detail_response, reverse("drawing_export_json", args=[drawing.id]))
        self.assertContains(detail_response, "Pobierz JSON")

@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DrawingDetailCleanUiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="clean_ui_user", password="password123")
        self.drawing = Drawing.objects.create(user=self.user, title="Clean UI", mode=Drawing.MODE_GEOMETRY, metadata={"debug": True})
        self.client.login(username="clean_ui_user", password="password123")

    def test_drawing_detail_hides_developer_notes_and_metadata(self):
        response = self.client.get(reverse("drawing_detail", args=[self.drawing.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Co robi ten krok MVP?")
        self.assertNotContains(response, "Document metadata")
        self.assertNotContains(response, "debug")

    def test_drawing_detail_does_not_show_refresh_button(self):
        response = self.client.get(reverse("drawing_detail", args=[self.drawing.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Odśwież")
        self.assertNotContains(response, "data-action=\"refresh\"")

    def test_drawing_detail_has_simplified_export_section(self):
        response = self.client.get(reverse("drawing_detail", args=[self.drawing.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Eksport")
        self.assertContains(response, "Pobierz TikZ")
        self.assertContains(response, "Pobierz JSON")
        self.assertContains(response, "Pokaż TikZ")
        self.assertContains(response, "Kopiuj TikZ")
        self.assertContains(response, "drawing-editor__export-button")
        self.assertContains(response, "drawing-editor__export-section--under-canvas")
        self.assertContains(response, "data-role=\"object-list\"")
        self.assertContains(response, "drawing-editor__objects-panel")
        self.assertNotContains(response, "Ten rysunek można już eksportować")
        self.assertNotContains(response, "Back")
        self.assertNotContains(response, "Delete")
        self.assertNotContains(response, "Eksport TikZ")

    def test_drawing_editor_js_has_no_refresh_button_handler(self):
        path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(path)
        source = Path(path).read_text()

        self.assertNotIn("data-action='refresh'", source)
        self.assertNotIn('data-action="refresh"', source)

@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DrawingEditorDrawerStep35Tests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="drawer_step35_user", password="password123")
        self.drawing = Drawing.objects.create(user=self.user, title="Drawer", mode=Drawing.MODE_GEOMETRY)
        self.client.login(username="drawer_step35_user", password="password123")

    def test_drawing_detail_contains_tabbed_edit_drawer(self):
        response = self.client.get(reverse("drawing_detail", args=[self.drawing.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-role="edit-drawer"')
        self.assertContains(response, 'data-panel-tab="object"')
        self.assertContains(response, 'data-panel-tab="style"')
        self.assertContains(response, 'data-panel-tab="settings"')
        self.assertContains(response, 'data-panel-tab="default-style"')
        self.assertContains(response, 'data-action="close-edit-drawer"')

    def test_drawing_editor_js_supports_edit_drawer_tabs_and_auto_open(self):
        path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(path)
        source = Path(path).read_text(encoding="utf-8")

        self.assertIn("selectPanelTab", source)
        self.assertIn("openEditPanel", source)
        self.assertIn("panelTabButtons", source)
        self.assertIn("closeEditDrawerButton", source)
        self.assertIn('this.openEditPanel("object")', source)

    def test_drawing_editor_js_hides_irrelevant_style_fields(self):
        path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(path)
        source = Path(path).read_text(encoding="utf-8")

        self.assertIn("updateVisibleStyleFields", source)
        self.assertIn("setStyleFieldVisible", source)
        self.assertIn('data-style-field', source)
        self.assertIn('object.type === "graph.edge"', source)

    def test_drawing_editor_css_contains_drawer_tab_styles(self):
        path = finders.find("routes/drawing_editor.css")
        self.assertIsNotNone(path)
        source = Path(path).read_text(encoding="utf-8")

        self.assertIn("drawing-editor__drawer-tabs", source)
        self.assertIn("drawing-editor__drawer-tab-button--active", source)
        self.assertIn("drawing-editor__drawer-close", source)
        self.assertIn("drawing-editor__drawer-section[hidden]", source)

@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DrawingEditorSvgPngExportStep36Tests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="export_step36_user", password="password123")
        self.drawing = Drawing.objects.create(user=self.user, title="Eksport wizualny", mode=Drawing.MODE_GEOMETRY)
        self.client.login(username="export_step36_user", password="password123")

    def test_drawing_detail_contains_svg_and_png_export_buttons(self):
        response = self.client.get(reverse("drawing_detail", args=[self.drawing.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pobierz SVG")
        self.assertContains(response, "Pobierz PNG")
        self.assertContains(response, 'data-action="download-svg"')
        self.assertContains(response, 'data-action="download-png"')
        self.assertContains(response, 'data-drawing-title="Eksport wizualny"')

    def test_drawing_editor_js_supports_svg_and_png_downloads(self):
        path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(path)
        source = Path(path).read_text(encoding="utf-8")

        self.assertIn("downloadSvg", source)
        self.assertIn("downloadPng", source)
        self.assertIn("serializedSvgForDownload", source)
        self.assertIn("XMLSerializer", source)
        self.assertIn("image/svg+xml", source)
        self.assertIn("image/png", source)
        self.assertIn("download-svg", source)
        self.assertIn("download-png", source)

@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DrawingEditorAdvancedStyleStep37Tests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="style_step37_user", password="password123")
        self.drawing = Drawing.objects.create(user=self.user, title="Style 37", mode=Drawing.MODE_GEOMETRY)
        self.client.login(username="style_step37_user", password="password123")

    def test_drawing_detail_contains_advanced_style_controls(self):
        response = self.client.get(reverse("drawing_detail", args=[self.drawing.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-role="style-line-dash"')
        self.assertContains(response, 'data-role="style-fill-opacity"')
        self.assertContains(response, 'data-role="style-stroke-opacity"')
        self.assertContains(response, 'data-role="style-font-size"')
        self.assertContains(response, 'data-role="style-label-position"')
        self.assertContains(response, 'Nad-prawo')
        self.assertContains(response, 'Przerywana')

    def test_drawing_editor_js_supports_label_positions_and_line_styles(self):
        path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(path)
        source = Path(path).read_text(encoding="utf-8")

        self.assertIn("labelPlacement", source)
        self.assertIn("labelPosition", source)
        self.assertIn("lineDashArray", source)
        self.assertIn("stroke-opacity", source)
        self.assertIn("fill-opacity", source)
        self.assertIn("styleLabelPositionInput", source)
        self.assertIn("styleLineDashInput", source)

    def test_tikz_export_contains_dashed_opacity_and_relative_label_position(self):
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="A",
            type="geometry.point",
            data={"x": 100, "y": 100, "label": "A"},
            style={
                "stroke": "#111827",
                "fill": "#ffffff",
                "lineDash": "dashed",
                "strokeOpacity": 0.5,
                "fillOpacity": 0.25,
                "labelPosition": "below-left",
                "fontSize": 20,
                "showLabel": True,
            },
        )

        response = self.client.get(reverse("drawing_export_tikz", args=[self.drawing.id]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("draw opacity=0.5", content)
        self.assertIn("fill opacity=0.25", content)
        self.assertIn("below left", content)
        self.assertIn("scale=", content)

@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DrawingStep39DuplicateVisibilityObjectListTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="step39_user", password="password123")
        self.other = User.objects.create_user(username="step39_other", password="password123")
        self.drawing = Drawing.objects.create(
            user=self.user,
            title="Rysunek do duplikacji",
            mode=Drawing.MODE_GEOMETRY,
            settings={"canvas": {"width": 900, "height": 520, "gridSize": 50, "showGrid": True, "snapToGrid": False}, "tikz": {"scale": 100}},
        )
        self.point = DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="A",
            type="geometry.point",
            data={"x": 100, "y": 100, "label": "A"},
            style={"stroke": "#111827", "fill": "#ffffff", "visible": True},
            order=0,
        )
        self.hidden = DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="B",
            type="geometry.point",
            data={"x": 200, "y": 100, "label": "B"},
            style={"stroke": "#111827", "fill": "#ffffff", "visible": False},
            order=1,
        )
        self.client.login(username="step39_user", password="password123")

    def test_drawing_list_contains_duplicate_button(self):
        response = self.client.get(reverse("drawing_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Duplikuj")
        self.assertContains(response, reverse("drawing_duplicate", args=[self.drawing.id]))

    def test_duplicate_drawing_copies_settings_and_objects(self):
        response = self.client.post(reverse("drawing_duplicate", args=[self.drawing.id]))
        self.assertEqual(response.status_code, 302)
        copy = Drawing.objects.exclude(id=self.drawing.id).get(user=self.user)
        self.assertEqual(copy.title, "Kopia: Rysunek do duplikacji")
        self.assertEqual(copy.mode, self.drawing.mode)
        self.assertEqual(copy.drawing_objects.count(), 2)
        copied_hidden = copy.drawing_objects.get(object_id="B")
        self.assertFalse(copied_hidden.style.get("visible", True))

    def test_other_user_cannot_duplicate_drawing(self):
        self.client.logout()
        self.client.login(username="step39_other", password="password123")
        response = self.client.post(reverse("drawing_duplicate", args=[self.drawing.id]))
        self.assertEqual(response.status_code, 404)

    def test_hidden_object_is_not_rendered_in_tikz_but_exported_json_keeps_visibility(self):
        response = self.client.get(reverse("drawing_export_tikz", args=[self.drawing.id]))
        self.assertEqual(response.status_code, 200)
        tikz = response.content.decode("utf-8")
        self.assertIn("(A)", tikz)
        self.assertIn("\\coordinate (B)", tikz)
        self.assertNotIn("$ B $", tikz)

        response = self.client.get(reverse("drawing_export_json", args=[self.drawing.id]))
        payload = json.loads(response.content.decode("utf-8"))
        hidden = next(obj for obj in payload["objects"] if obj["object_id"] == "B")
        self.assertFalse(hidden["style"].get("visible", True))

    def test_drawing_detail_contains_visibility_control_and_improved_object_list_hooks(self):
        response = self.client.get(reverse("drawing_detail", args=[self.drawing.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-role="style-visible"')
        self.assertContains(response, "Widoczny na rysunku")
        self.assertContains(response, 'data-role="object-list"')

    def test_drawing_editor_js_supports_visibility_toggle_and_better_object_list(self):
        path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(path)
        source = Path(path).read_text(encoding="utf-8")
        self.assertIn("objectIsVisible", source)
        self.assertIn("toggleObjectVisibility", source)
        self.assertIn("objectTypeLabel", source)
        self.assertIn("objectShortSummary", source)
        self.assertIn("toggle-object-visibility", source)

@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DrawingStep40PlotImprovementsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="step40_user", password="password123")
        self.drawing = Drawing.objects.create(user=self.user, title="Wykres pomiarowy", mode=Drawing.MODE_PLOT)
        self.client.login(username="step40_user", password="password123")

    def test_plot_chart_accepts_points_with_measurement_uncertainties(self):
        payload = {
            "object_id": "chart_errors",
            "type": "plot.chart",
            "data": {
                "series": [{
                    "label": "Pomiary",
                    "plotType": "scatter",
                    "points": [[618, 2.6, 8, 0.03], [699, 3.59, 8, 0.02]],
                    "style": {"stroke": "#0000ff"},
                }],
                "functions": [],
                "axis": {"xMin": 600, "xMax": 720, "yMin": 2, "yMax": 4},
                "legend": {"show": True},
            },
            "style": {},
        }
        response = self.client.post(
            reverse("drawing_objects_collection", args=[self.drawing.id]),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        chart = self.drawing.drawing_objects.get(object_id="chart_errors")
        self.assertEqual(chart.data["series"][0]["points"][0], [618, 2.6, 8, 0.03])

    def test_tikz_export_uses_pgfplots_error_bars_and_continuous_functions(self):
        DrawingObject.objects.create(
            drawing=self.drawing,
            object_id="chart",
            type="plot.chart",
            data={
                "series": [{
                    "label": "Pomiary",
                    "plotType": "scatter",
                    "points": [[618, 2.6, 8, 0.03], [699, 3.59, 8, 0.02]],
                    "style": {"stroke": "#0000ff"},
                }],
                "functions": [{
                    "expression": "0.013551251019349148 * x - 5.800802068110081",
                    "domainMin": 0,
                    "domainMax": 1500,
                    "label": "dopasowanie",
                    "color": "#0000ff",
                    "samples": 10,
                }],
                "axis": {"xMin": 0, "xMax": 1500, "yMin": 0, "yMax": 15},
                "legend": {"show": True},
            },
            style={},
        )
        response = self.client.get(reverse("drawing_export_tikz", args=[self.drawing.id]))
        self.assertEqual(response.status_code, 200)
        tikz = response.content.decode("utf-8")
        self.assertIn("error bars/.cd", tikz)
        self.assertIn("(618, 2.6) +- (8, 0.03)", tikz)
        self.assertIn("domain=0:1500", tikz)
        self.assertIn("samples=10", tikz)
        self.assertIn("{0.013551251019349148 * x - 5.800802068110081};", tikz)
        self.assertNotIn("coordinates {\n      (0,", tikz)

    def test_drawing_editor_js_supports_dynamic_plot_axes_and_error_bars(self):
        path = finders.find("routes/drawing_editor.js")
        self.assertIsNotNone(path)
        source = Path(path).read_text(encoding="utf-8")
        self.assertIn("plotAxisCanvasPosition", source)
        self.assertIn("xError", source)
        self.assertIn("yError", source)
        self.assertIn("drawing-plot-errorbar", source)
        self.assertIn("plotFunctionSamplesInput", source)

    def test_plot_ui_mentions_error_bar_format_and_samples(self):
        response = self.client.get(reverse("drawing_detail", args=[self.drawing.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "x,y +- dx,dy")
        self.assertContains(response, "Liczba próbek")
