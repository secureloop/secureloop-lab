# Download a Debian cloud image
wget https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2

# Create cloud-init config files
cat > user-data <<EOF
#cloud-config
hostname: debian-cloud
users:
  - name: tonit
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - ssh-rsa YOUR_SSH_PUBLIC_KEY_HERE
packages:
  - vim
  - htop
EOF

cat > meta-data <<EOF
instance-id: debian-001
local-hostname: debian-cloud
EOF

# Create cloud-init ISO
sudo apt install cloud-image-utils  # or genisoimage
cloud-localds cloud-init.iso user-data meta-data

# Import the VM with cloud-init
virt-install \
  --name debian-cloud \
  --memory 4096 \
  --vcpus 4 \
  --disk /var/lib/libvirt/images/debian-12-generic-amd64.qcow2,bus=virtio \
  --disk cloud-init.iso,device=cdrom \
  --os-variant debian12 \
  --network network=default \
  --graphics none \
  --console pty,target_type=serial \
  --import
