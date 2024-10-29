import add_pypath
import os
import argparse
import time
import viser
import viser.transforms as vtf
import json
from tqdm.auto import tqdm
from PIL import Image
import numpy as np
import torch

parser = argparse.ArgumentParser()
parser.add_argument("--cameras", default="cameras.json", required=True, type=str)
parser.add_argument("--points", default=None, type=str)
parser.add_argument("--point-sparsify", type=int, default=1)
parser.add_argument("--images", default=None, type=str)
parser.add_argument("--up", nargs="+", required=False, type=float, default=None)
parser.add_argument("--camera-scale", type=float, default=0.02)
parser.add_argument("--point-size", type=float, default=0.002)
args = parser.parse_args()

with open(args.cameras, "r") as f:
    camera_poses = json.load(f)

viser_server = viser.ViserServer()

camera_transform = torch.eye(4, dtype=torch.float)

camera_pose_transform = np.linalg.inv(camera_transform.cpu().numpy())
up = torch.zeros(3)
for camera in tqdm(camera_poses, leave=False, desc="Loading images"):
    name = camera["img_name"]
    c2w = np.eye(4)
    c2w[:3, :3] = np.asarray(camera["rotation"])
    c2w[:3, 3] = np.asarray(camera["position"])
    c2w[:3, 1:3] *= -1
    c2w = np.matmul(camera_pose_transform, c2w)

    R = vtf.SO3.from_matrix(c2w[:3, :3])
    R = R @ vtf.SO3.from_x_radians(np.pi)

    cx = camera["width"] // 2
    cy = camera["height"] // 2
    fx = camera["fx"]

    image_file_path = None
    if args.images is not None:
        image_file_path = os.path.join(args.images, name)
        if not os.path.exists(image_file_path):
            print("[WARNING] {} not found".format(image_file_path))
            image_file_path = None

    shape = np.asarray([camera["height"], camera["width"]])
    shape = (shape / shape.max() * 100).astype(np.int32)

    if image_file_path is None:
        image = np.ones((shape[0], shape[1], 3), dtype=np.uint8) * camera.get("color", (200, 0, 0))
    else:
        pil_image = Image.open(image_file_path).convert("RGB").resize((shape[1], shape[0]))
        image = np.asarray(pil_image)

    camera_handle = viser_server.scene.add_camera_frustum(
        name="cameras/{}".format(name),
        fov=float(2 * np.arctan(cx / fx)),
        scale=args.camera_scale,
        aspect=float(cx / cy),
        wxyz=R.wxyz,
        position=c2w[:3, 3],
        color=camera.get("color", (255, 0, 0)),
        image=image,
    )

    up += torch.tensor(camera["rotation"])[:3, 1]
up *= -1

if args.up is not None:
    up = torch.tensor(args.up)
print("up vector = {}".format(up))
up = up / torch.linalg.norm(up)

if args.points is not None:
    from internal.utils.graphics_utils import fetch_ply_without_rgb_normalization

    pcd = fetch_ply_without_rgb_normalization(args.points)
    viser_server.scene.add_point_cloud(
        "points",
        pcd.points[::args.point_sparsify],
        pcd.colors[::args.point_sparsify],
        point_size=args.point_size,
    )

reset_up_button = viser_server.gui.add_button(
    "Reset up direction",
    icon=viser.Icon.ARROW_AUTOFIT_UP,
    hint="Reset the orbit up direction.",
)


@reset_up_button.on_click
def _(event: viser.GuiEvent) -> None:
    assert event.client is not None
    event.client.camera.up_direction = vtf.SO3(event.client.camera.wxyz) @ np.array([0.0, -1.0, 0.0])


viser_server.scene.set_up_direction(up)


while True:
    time.sleep(1 << 15)
