Klipper Adaptive Bed Mesh
===
[中文版](readme_zh_cn.md)

# What is it?


# Install via Moonraker
Clone the repository to the home directory

    cd ~
    git clone https://github.com/eamars/klipper_adaptive_bed_mesh.git

You need to manually install the plugin for the first time. It will prompt for password to restart the Klipper process. 
    
    source klipper_adaptive_bed_mesh/install.sh

Then copy the below block into the moonraker.conf to allow automatic update.

    [update_manager client klipper_adaptive_bed_mesh]
    type: git_repo
    primary_branch: main
    path: ~/klipper_adaptive_bed_mesh
    origin: https://github.com/eamars/klipper_adaptive_bed_mesh.git
    install_script: install.sh

# Configurations
The `[adaptive_bed_mesh]` section along with required parameters need to be declared under `printer.cfg`. 

    [adaptive_bed_mesh]
