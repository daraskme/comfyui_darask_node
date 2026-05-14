# DARASK RIFE Interpolation — internal model code.
#
# The architecture and training-log Python modules under this package
# (model/warplayer.py, model/loss.py, model/pytorch_msssim/__init__.py,
# train_log/IFNet_HDv3.py, train_log/RIFE_HDv3.py, train_log/refine.py)
# are derived from the original RIFE reference implementation by
# Zhewei Huang et al. (hzwer), licensed under the MIT License:
# https://github.com/megvii-research/ECCV2022-RIFE
# https://github.com/hzwer/Practical-RIFE
#
# They are bundled here so DARASK's RIFE Interpolation node can run as a
# self-contained custom node, without depending on any specific third-party
# ComfyUI-VFI install. The ComfyUI node wrapper itself (rife_loader.py)
# is original to this project and licensed under the same terms as the
# rest of comfyui_darask_node (MIT).
