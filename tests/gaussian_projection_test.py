import os

import torch

os.environ["PATH"] = "/usr/local/cuda-11.8/bin:{}".format(os.environ["PATH"])
os.environ["LD_LIBRARY_PATH"] = "/usr/local/cuda-11.8/lib64"

import unittest
from matplotlib import pyplot as plt
from gsplat.sh import spherical_harmonics
from gsplat.rasterize import rasterize_gaussians
from internal.utils.gaussian_projection import project_gaussians
from internal.utils.ssim import ssim

from internal.models.gaussian_model import GaussianModel
from internal.renderers.vanilla_renderer import VanillaRenderer
from internal.renderers.pypreprocess_gsplat_renderer import PythonPreprocessGSplatRenderer
from internal.dataparsers.colmap_dataparser import ColmapParams, ColmapDataParser


class GaussianProjectionTestCase(unittest.TestCase):
    model: GaussianModel = None

    def test_project_gaussians(self):
        dtype, device = torch.float, torch.device("cpu")

        # [rect=0, True, filter_by_depth, True]
        means_3d = torch.tensor([[4.9744410514831543, -1.6869305372238159, -1.0178891420364380],
                                 [0.1855451613664627, 0.2173379510641098, -1.6864157915115356],
                                 [14.9114608764648438, -4.6346273422241211, 1.8997575044631958],
                                 [5.0085635185241699, -3.8657102584838867, -1.3707503080368042]], dtype=dtype, device=device, requires_grad=True)
        scales = torch.tensor([[0.1152868643403053, 0.0463323593139648, 0.0125905377790332],
                               [0.0036764058750123, 0.0155582446604967, 0.0025763553567231],
                               [0.0729999020695686, 0.1261776685714722, 0.0579524375498295],
                               [1.8269745111465454, 0.1552953571081161, 0.2113087177276611]], dtype=dtype, device=device, requires_grad=True)
        rotations = torch.tensor([[0.6251348853111267, -0.7321968674659729, 0.2666733860969543,
                                   0.0444900505244732],
                                  [0.9881987571716309, -0.0445680879056454, -0.1419259905815125,
                                   0.0365220829844475],
                                  [0.9662694931030273, 0.1446461081504822, -0.1685470491647720,
                                   0.1303553283214569],
                                  [0.8739961385726929, -0.3649578392505646, 0.1373531222343445,
                                   -0.2899493575096130]], dtype=dtype, device=device, requires_grad=True)

        width = torch.tensor(1297, dtype=torch.int, device=device)
        height = torch.tensor(840, dtype=torch.int, device=device)
        focal_x = torch.tensor(961.4099731445312500, dtype=dtype, device=device)
        focal_y = torch.tensor(962.8024902343750000, dtype=dtype, device=device)
        cx = torch.tensor(648.5000000000000000, dtype=dtype, device=device)
        cy = torch.tensor(420., dtype=dtype, device=device)

        world_to_camera = torch.tensor([
            [9.9991554021835327e-01, -1.2848137877881527e-02,
             -1.9360868027433753e-03, 0.0000000000000000e+00],
            [-5.9221056289970875e-04, -1.9391909241676331e-01,
             9.8101717233657837e-01, 0.0000000000000000e+00],
            [-1.2979693710803986e-02, -9.8093330860137939e-01,
             -1.9391019642353058e-01, 0.0000000000000000e+00],
            [-3.2830274105072021e-01, -1.9259561300277710e+00,
             3.9580578804016113e+00, 1.0000000000000000e+00],
        ], dtype=dtype, device=device)

        xys, depths, radii, conics, comp, num_tiles_hit, cov3d, mask = project_gaussians(
            means_3d=means_3d,
            scales=scales,
            scale_modifier=1.,
            quaternions=rotations,
            world_to_camera=world_to_camera,
            fx=focal_x,
            fy=focal_y,
            cx=cx,
            cy=cy,
            img_height=height,
            img_width=width,
            block_width=16,
        )

        # make sure that back propagation works
        torch.sum(xys).backward(retain_graph=True)
        torch.sum(depths).backward(retain_graph=True)
        torch.sum(conics).backward(retain_graph=True)

        self.assertTrue(torch.all(mask == torch.tensor([False, True, False, True], dtype=torch.bool, device=device)))
        self.assertTrue(torch.allclose(xys[mask], torch.tensor([
            [622.1340942382812500, 351.8106079101562500],
            [11359.6181640625000000, 656.7397460937500000],
        ], dtype=dtype, device=device) + 0.5))
        self.assertTrue(torch.all(radii == torch.tensor([0, 4, 0, 16783], dtype=radii.dtype, device=device)))
        self.assertTrue(torch.allclose(conics[mask], torch.tensor([
            [1.1229337453842163e+00, 1.4079402387142181e-01,
             1.5783417224884033e+00],
            [2.3913329982860887e-07, -9.6377800673508318e-07,
             4.5153879000281449e-06],
        ], dtype=dtype, device=device)))
        self.assertTrue(torch.allclose(comp[mask], torch.tensor([0.5893613696098328, 0.9999994039535522], dtype=comp.dtype, device=comp.device)))
        self.assertTrue(torch.all(num_tiles_hit[mask] == torch.tensor([4, 4346], dtype=num_tiles_hit.dtype, device=device)))
        self.assertTrue(torch.allclose(cov3d[mask].reshape((-1, 9))[:, [0, 1, 2, 4, 5, 8]], torch.tensor([
            [1.3772079910268076e-05, -1.3363457583182026e-05,
             3.2048776574811200e-06, 2.3899228835944086e-04,
             -2.2861815523356199e-05, 9.4481683845515363e-06],
            [2.1180632114410400e+00, -1.5923748016357422e+00,
             -6.8420924246311188e-02, 1.2517973184585571e+00,
             6.5218225121498108e-02, 3.6743372678756714e-02],
        ], dtype=dtype, device=device)))

    def load_model_and_dataset(self):
        if self.model is None:
            self.model, self.renderer = GaussianModel(sh_degree=3), VanillaRenderer()
            self.model.load_ply("../outputs/garden/down_sample_4/point_cloud/iteration_30000/point_cloud.ply", device="cuda")
            print("Gaussian count: {}".format(self.model.get_xyz.shape[0]))
            # dataset
            self.dataparser_outputs = ColmapDataParser(
                os.path.expanduser("~/data/Mip-NeRF360/garden"),
                os.path.abspath(""),
                global_rank=0,
                params=ColmapParams(
                    split_mode="experiment",
                    reorient=True,
                    down_sample_factor=4,
                ),
            ).get_outputs()

    def test_project_gaussians_by_rasterize(self):
        self.load_model_and_dataset()
        camera = self.dataparser_outputs.test_set.cameras[0].to_device(self.model.get_xyz.device)

        xys, depths, radii, conics, comp, num_tiles_hit, cov3d, mask = project_gaussians(
            means_3d=self.model.get_xyz,
            scales=self.model.get_scaling,
            scale_modifier=1.,
            quaternions=self.model.get_rotation / self.model.get_rotation.norm(dim=-1, keepdim=True),
            world_to_camera=camera.world_to_camera,
            fx=camera.fx,
            fy=camera.fy,
            cx=camera.cx,
            cy=camera.cy,
            img_height=camera.height,
            img_width=camera.width,
            block_width=16,
        )

        xys.retain_grad()

        viewdirs = self.model.get_xyz.detach() - camera.camera_center  # (N, 3)
        viewdirs = viewdirs / viewdirs.norm(dim=-1, keepdim=True)
        rgbs = spherical_harmonics(self.model.active_sh_degree, viewdirs, self.model.get_features)
        rgbs = torch.clamp(rgbs + 0.5, min=0.0)  # type: ignore

        opacities = self.model.get_opacity
        opacities = opacities * comp[:, None]

        rgb, alpha = rasterize_gaussians(  # type: ignore
            xys,
            depths,
            radii,
            conics,
            num_tiles_hit,  # type: ignore
            rgbs,
            opacities,
            int(camera.height.item()),
            int(camera.width.item()),
            16,
            background=torch.tensor([0., 0., 0.], dtype=torch.float, device=xys.device),
            return_alpha=True,
        )  # type: ignore
        plt.imshow(rgb.detach().cpu().numpy())
        plt.show()

        gt_image = torch.ones_like(rgb, requires_grad=False) * 0.5
        l1 = torch.abs(rgb - gt_image).mean()
        ssim_metric = ssim(rgb, gt_image)
        loss = 0.8 * l1 + 0.2 * (1. - ssim_metric)
        loss.backward()

    def test_pyprocess_gsplat_renderer(self):
        self.load_model_and_dataset()
        camera = self.dataparser_outputs.test_set.cameras[0].to_device(self.model.get_xyz.device)

        renderer = PythonPreprocessGSplatRenderer()
        results = renderer(camera, self.model, torch.zeros((3,), dtype=torch.float, device=self.model.get_xyz.device))

        rgb = results["render"]
        gt_image = torch.ones_like(rgb, requires_grad=False) * 0.5
        l1 = torch.abs(rgb - gt_image).mean()
        ssim_metric = ssim(rgb, gt_image)
        loss = 0.8 * l1 + 0.2 * (1. - ssim_metric)
        loss.backward()

        plt.imshow(rgb.detach().permute(1, 2, 0).cpu().numpy())
        plt.show()

    if __name__ == '__main__':
        unittest.main()
