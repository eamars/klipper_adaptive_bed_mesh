Klipper 自适应网床
===
[English](readme.md)

# 关于插件


# 安装（集成 Moonraker）
将代码同步到当前用户根目录。

    cd ~
    git clone https://github.com/eamars/klipper_adaptive_bed_mesh.git

第一次安装时需要执行安装脚本。

    source klipper_adaptive_bed_mesh/install.sh

同时将以下内容复制到 moonraker.conf 以开启自动更新检查。

    [update_manager client klipper_adaptive_bed_mesh]
    type: git_repo
    primary_branch: main
    path: ~/klipper_adaptive_bed_mesh
    origin: https://github.com/eamars/klipper_adaptive_bed_mesh.git
    install_script: install.sh

# 示例配置
用户需要将以下内容根据实际配置复制到`printer.cfg`当中。

    [adaptive_bed_mesh]
