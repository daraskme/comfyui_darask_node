# Derived from hzwer's RIFE (MIT License) and the ComfyUI-VFI inference
# wrapper. Only the inference path is needed at runtime — training-only
# bits (VGG loss, distillation teacher) are stubbed out.
# https://github.com/megvii-research/ECCV2022-RIFE
import torch

from .IFNet_HDv3 import IFNet

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class Model:
    """Inference-only RIFE Model wrapper."""

    def __init__(self, local_rank=-1):
        self.flownet = IFNet()
        self.device()
        self.version = 4.25

    def train(self):
        self.flownet.train()

    def eval(self):
        self.flownet.eval()

    def device(self):
        self.flownet.to(device)

    def load_model(self, path, rank=0):
        def convert(param):
            if rank == -1:
                return {k.replace("module.", ""): v for k, v in param.items() if "module." in k}
            else:
                return param

        if rank <= 0:
            if torch.cuda.is_available():
                try:
                    self.flownet.load_state_dict(convert(torch.load(path, weights_only=True)), False)
                except TypeError:
                    self.flownet.load_state_dict(convert(torch.load(path)), False)
            else:
                try:
                    self.flownet.load_state_dict(
                        convert(torch.load(path, map_location="cpu", weights_only=True)),
                        False,
                    )
                except TypeError:
                    self.flownet.load_state_dict(
                        convert(torch.load(path, map_location="cpu")),
                        False,
                    )

    def inference(self, img0, img1, timestep=0.5, scale=1.0):
        imgs = torch.cat((img0, img1), 1)
        scale_list = [16 / scale, 8 / scale, 4 / scale, 2 / scale, 1 / scale]
        flow, mask, merged = self.flownet(imgs, timestep, scale_list)
        result = merged[-1]
        del flow, mask, merged
        return result

    def inference_batch(self, batch_img0, batch_img1, timesteps, scale=1.0):
        """Process multiple frame pairs in sequence (per-pair calls) to keep memory bounded."""
        batch_size = batch_img0.shape[0]
        imgs = torch.cat((batch_img0, batch_img1), 1)
        scale_list = [16 / scale, 8 / scale, 4 / scale, 2 / scale, 1 / scale]
        if isinstance(timesteps, list):
            timesteps = torch.tensor(timesteps, device=batch_img0.device, dtype=batch_img0.dtype)
        results = []
        for i in range(batch_size):
            ts = timesteps[i] if timesteps.dim() > 0 else timesteps
            flow, mask, merged = self.flownet(imgs[i : i + 1], ts, scale_list)
            results.append(merged[-1])
            del flow, mask, merged
        return torch.cat(results, dim=0)
