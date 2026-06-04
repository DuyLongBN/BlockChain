// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title LicensePlateRegistry
 * @dev Smart Contract quản lý và xác thực biển số xe Việt Nam
 * @notice Hệ thống đăng ký, xác thực, chuyển nhượng biển số xe trên Blockchain
 */
contract LicensePlateRegistry {
    
    // ============ STRUCTS ============
    
    struct Vehicle {
        string plateNumber;      // Biển số xe (e.g., "30G-493.44")
        string ownerName;        // Tên chủ xe
        string vehicleType;      // Loại xe (Ô tô, Xe máy, ...)
        string color;            // Màu xe
        string province;         // Tỉnh/Thành phố
        uint256 registeredAt;    // Thời gian đăng ký (timestamp)
        uint256 lastUpdated;     // Thời gian cập nhật cuối
        bool isActive;           // Trạng thái hoạt động
        address registeredBy;    // Địa chỉ ví đăng ký
    }
    
    struct TransferRecord {
        string previousOwner;    // Chủ cũ
        string newOwner;         // Chủ mới
        uint256 transferredAt;   // Thời gian chuyển nhượng
        address transferredBy;   // Địa chỉ ví thực hiện
    }
    
    struct VerificationLog {
        string plateNumber;      // Biển số được xác thực
        bool isValid;            // Kết quả xác thực
        uint256 verifiedAt;      // Thời gian xác thực
        address verifiedBy;      // Địa chỉ ví xác thực
    }
    
    struct Violation {
        string description;      // Mô tả lỗi vi phạm
        uint256 fineAmount;      // Số tiền phạt
        uint256 timestamp;       // Thời gian vi phạm
        bool isPaid;             // Đã nộp phạt chưa
    }
    
    // ============ STATE VARIABLES ============
    
    address public admin;                                           // Admin address
    mapping(string => Vehicle) private vehicles;                    // plateNumber => Vehicle
    mapping(string => TransferRecord[]) private transferHistory;    // plateNumber => transfers
    mapping(string => Violation[]) private violations;              // plateNumber => violations
    string[] private allPlateNumbers;                               // Danh sách tất cả biển số
    VerificationLog[] private verificationLogs;                     // Log xác thực
    uint256 public totalRegistered;                                 // Tổng số xe đã đăng ký
    uint256 public totalVerifications;                              // Tổng số lần xác thực
    uint256 public totalTransfers;                                  // Tổng số lần chuyển nhượng
    uint256 public totalViolations;                                 // Tổng số lỗi vi phạm
    
    // ============ EVENTS ============
    
    event PlateRegistered(
        string plateNumber, 
        string ownerName, 
        string vehicleType,
        string province,
        uint256 timestamp
    );
    
    event PlateVerified(
        string plateNumber, 
        bool isValid, 
        uint256 timestamp
    );
    
    event OwnershipTransferred(
        string plateNumber, 
        string previousOwner, 
        string newOwner, 
        uint256 timestamp
    );

    event VehicleUpdated(
        string plateNumber,
        string vehicleType,
        string color,
        string province,
        uint256 timestamp
    );
    
    event PlateDeactivated(
        string plateNumber,
        uint256 timestamp
    );

    event PlateReactivated(
        string plateNumber,
        uint256 timestamp
    );
    
    event ViolationAdded(
        string plateNumber,
        string description,
        uint256 fineAmount,
        uint256 timestamp
    );

    event ViolationPaid(
        string plateNumber,
        uint256 violationIndex,
        uint256 timestamp
    );
    
    // ============ MODIFIERS ============
    
    modifier onlyAdmin() {
        require(msg.sender == admin, "Only admin can perform this action");
        _;
    }
    
    // ============ CONSTRUCTOR ============
    
    constructor() {
        admin = msg.sender;
    }
    
    // ============ MAIN FUNCTIONS ============
    
    /**
     * @dev Đăng ký biển số xe mới
     * @param _plateNumber Biển số xe
     * @param _ownerName Tên chủ xe
     * @param _vehicleType Loại xe
     * @param _color Màu xe
     * @param _province Tỉnh/Thành phố
     */
    function registerPlate(
        string memory _plateNumber,
        string memory _ownerName,
        string memory _vehicleType,
        string memory _color,
        string memory _province
    ) public onlyAdmin {
        // Kiểm tra biển số chưa tồn tại
        require(bytes(vehicles[_plateNumber].plateNumber).length == 0, "Plate already exists; use reactivatePlate");
        require(bytes(_plateNumber).length > 0, "Plate number cannot be empty");
        require(bytes(_ownerName).length > 0, "Owner name cannot be empty");
        
        // Tạo bản ghi mới
        vehicles[_plateNumber] = Vehicle({
            plateNumber: _plateNumber,
            ownerName: _ownerName,
            vehicleType: _vehicleType,
            color: _color,
            province: _province,
            registeredAt: block.timestamp,
            lastUpdated: block.timestamp,
            isActive: true,
            registeredBy: msg.sender
        });
        
        allPlateNumbers.push(_plateNumber);
        totalRegistered++;
        
        emit PlateRegistered(_plateNumber, _ownerName, _vehicleType, _province, block.timestamp);
    }
    
    /**
     * @dev Xác thực biển số xe có tồn tại trên blockchain
     * @param _plateNumber Biển số cần xác thực
     * @return isValid Biển số có hợp lệ không
     * @return ownerName Tên chủ xe (nếu hợp lệ)
     * @return vehicleType Loại xe
     * @return registeredAt Thời gian đăng ký
     */
    function verifyPlate(string memory _plateNumber) public returns (
        bool isValid,
        string memory ownerName,
        string memory vehicleType,
        uint256 registeredAt
    ) {
        Vehicle memory v = vehicles[_plateNumber];
        isValid = v.isActive;
        
        // Ghi log xác thực
        verificationLogs.push(VerificationLog({
            plateNumber: _plateNumber,
            isValid: isValid,
            verifiedAt: block.timestamp,
            verifiedBy: msg.sender
        }));
        totalVerifications++;
        
        emit PlateVerified(_plateNumber, isValid, block.timestamp);
        
        if (isValid) {
            return (true, v.ownerName, v.vehicleType, v.registeredAt);
        } else {
            return (false, "", "", 0);
        }
    }
    
    /**
     * @dev Lấy thông tin chi tiết biển số (view - không tốn gas)
     * @param _plateNumber Biển số cần tra cứu
     */
    function getPlateInfo(string memory _plateNumber) public view returns (
        string memory plateNumber,
        string memory ownerName,
        string memory vehicleType,
        string memory color,
        string memory province,
        uint256 registeredAt,
        uint256 lastUpdated,
        bool isActive
    ) {
        Vehicle memory v = vehicles[_plateNumber];
        return (
            v.plateNumber,
            v.ownerName,
            v.vehicleType,
            v.color,
            v.province,
            v.registeredAt,
            v.lastUpdated,
            v.isActive
        );
    }
    
    /**
     * @dev Kiểm tra nhanh biển số có tồn tại (view - không tốn gas)
     * @param _plateNumber Biển số cần kiểm tra
     */
    function isPlateRegistered(string memory _plateNumber) public view returns (bool) {
        return vehicles[_plateNumber].isActive;
    }
    
    /**
     * @dev Chuyển nhượng chủ sở hữu xe
     * @param _plateNumber Biển số xe
     * @param _newOwner Tên chủ mới
     */
    function transferOwnership(
        string memory _plateNumber,
        string memory _newOwner
    ) public onlyAdmin {
        require(vehicles[_plateNumber].isActive, "Plate not registered or deactivated");
        require(bytes(_newOwner).length > 0, "New owner name cannot be empty");
        
        string memory previousOwner = vehicles[_plateNumber].ownerName;
        
        // Ghi lịch sử chuyển nhượng
        transferHistory[_plateNumber].push(TransferRecord({
            previousOwner: previousOwner,
            newOwner: _newOwner,
            transferredAt: block.timestamp,
            transferredBy: msg.sender
        }));
        
        // Cập nhật chủ sở hữu
        vehicles[_plateNumber].ownerName = _newOwner;
        vehicles[_plateNumber].lastUpdated = block.timestamp;
        totalTransfers++;
        
        emit OwnershipTransferred(_plateNumber, previousOwner, _newOwner, block.timestamp);
    }

    /**
     * @dev Cap nhat thong tin phuong tien, khong thay doi chu so huu hoac trang thai active
     * @param _plateNumber Bien so xe
     * @param _vehicleType Loai xe moi
     * @param _color Mau xe moi
     * @param _province Tinh/Thanh pho moi
     */
    function updateVehicle(
        string memory _plateNumber,
        string memory _vehicleType,
        string memory _color,
        string memory _province
    ) public onlyAdmin {
        require(bytes(vehicles[_plateNumber].plateNumber).length > 0, "Plate not found");

        vehicles[_plateNumber].vehicleType = _vehicleType;
        vehicles[_plateNumber].color = _color;
        vehicles[_plateNumber].province = _province;
        vehicles[_plateNumber].lastUpdated = block.timestamp;

        emit VehicleUpdated(_plateNumber, _vehicleType, _color, _province, block.timestamp);
    }
    
    /**
     * @dev Vô hiệu hóa biển số (chỉ admin)
     * @param _plateNumber Biển số cần vô hiệu hóa
     */
    function deactivatePlate(string memory _plateNumber) public onlyAdmin {
        require(vehicles[_plateNumber].isActive, "Plate not active");
        vehicles[_plateNumber].isActive = false;
        vehicles[_plateNumber].lastUpdated = block.timestamp;
        
        emit PlateDeactivated(_plateNumber, block.timestamp);
    }

    /**
     * @dev Kich hoat lai bien so da bi vo hieu hoa (chi admin)
     * @param _plateNumber Bien so can kich hoat lai
     */
    function reactivatePlate(string memory _plateNumber) public onlyAdmin {
        require(bytes(vehicles[_plateNumber].plateNumber).length > 0, "Plate not found");
        require(!vehicles[_plateNumber].isActive, "Plate already active");

        vehicles[_plateNumber].isActive = true;
        vehicles[_plateNumber].lastUpdated = block.timestamp;

        emit PlateReactivated(_plateNumber, block.timestamp);
    }
    
    /**
     * @dev Thêm lỗi vi phạm giao thông (chỉ admin)
     * @param _plateNumber Biển số vi phạm
     * @param _description Mô tả lỗi (e.g. "Vượt đèn đỏ")
     * @param _fineAmount Số tiền phạt (VNĐ)
     */
    function addViolation(
        string memory _plateNumber,
        string memory _description,
        uint256 _fineAmount
    ) public onlyAdmin {
        require(bytes(_plateNumber).length > 0, "Plate number empty");
        require(bytes(_description).length > 0, "Description empty");
        
        violations[_plateNumber].push(Violation({
            description: _description,
            fineAmount: _fineAmount,
            timestamp: block.timestamp,
            isPaid: false
        }));
        
        totalViolations++;
        emit ViolationAdded(_plateNumber, _description, _fineAmount, block.timestamp);
    }

    /**
     * @dev Danh dau mot loi vi pham da nop phat
     * @param _plateNumber Bien so vi pham
     * @param _violationIndex Vi tri loi vi pham trong danh sach getViolations
     */
    function markViolationPaid(
        string memory _plateNumber,
        uint256 _violationIndex
    ) public onlyAdmin {
        require(bytes(vehicles[_plateNumber].plateNumber).length > 0, "Plate not found");
        require(_violationIndex < violations[_plateNumber].length, "Violation index out of bounds");
        require(!violations[_plateNumber][_violationIndex].isPaid, "Violation already paid");

        violations[_plateNumber][_violationIndex].isPaid = true;

        emit ViolationPaid(_plateNumber, _violationIndex, block.timestamp);
    }
    
    // ============ GETTER FUNCTIONS ============
    
    /**
     * @dev Lấy tổng số biển số đã đăng ký
     */
    function getTotalPlates() public view returns (uint256) {
        return allPlateNumbers.length;
    }
    
    /**
     * @dev Lấy biển số tại index
     */
    function getPlateAtIndex(uint256 index) public view returns (string memory) {
        require(index < allPlateNumbers.length, "Index out of bounds");
        return allPlateNumbers[index];
    }
    
    /**
     * @dev Lấy lịch sử chuyển nhượng
     */
    function getTransferHistory(string memory _plateNumber) public view returns (
        string[] memory previousOwners,
        string[] memory newOwners,
        uint256[] memory timestamps
    ) {
        TransferRecord[] memory records = transferHistory[_plateNumber];
        uint256 len = records.length;
        
        previousOwners = new string[](len);
        newOwners = new string[](len);
        timestamps = new uint256[](len);
        
        for (uint256 i = 0; i < len; i++) {
            previousOwners[i] = records[i].previousOwner;
            newOwners[i] = records[i].newOwner;
            timestamps[i] = records[i].transferredAt;
        }
        
        return (previousOwners, newOwners, timestamps);
    }
    
    /**
     * @dev Lấy số lượng log xác thực
     */
    function getVerificationLogCount() public view returns (uint256) {
        return verificationLogs.length;
    }
    
    /**
     * @dev Lấy log xác thực tại index
     */
    function getVerificationLog(uint256 index) public view returns (
        string memory plateNumber,
        bool isValid,
        uint256 verifiedAt
    ) {
        require(index < verificationLogs.length, "Index out of bounds");
        VerificationLog memory log = verificationLogs[index];
        return (log.plateNumber, log.isValid, log.verifiedAt);
    }
    
    /**
     * @dev Lấy thống kê tổng quan
     */
    function getStatistics() public view returns (
        uint256 _totalRegistered,
        uint256 _totalVerifications,
        uint256 _totalTransfers,
        uint256 _totalViolations,
        uint256 _totalPlates
    ) {
        return (totalRegistered, totalVerifications, totalTransfers, totalViolations, allPlateNumbers.length);
    }
    
    /**
     * @dev Lấy danh sách vi phạm của một biển số
     */
    function getViolations(string memory _plateNumber) public view returns (
        string[] memory descriptions,
        uint256[] memory fineAmounts,
        uint256[] memory timestamps,
        bool[] memory paymentStatuses
    ) {
        Violation[] memory plateViolations = violations[_plateNumber];
        uint256 len = plateViolations.length;
        
        descriptions = new string[](len);
        fineAmounts = new uint256[](len);
        timestamps = new uint256[](len);
        paymentStatuses = new bool[](len);
        
        for (uint256 i = 0; i < len; i++) {
            descriptions[i] = plateViolations[i].description;
            fineAmounts[i] = plateViolations[i].fineAmount;
            timestamps[i] = plateViolations[i].timestamp;
            paymentStatuses[i] = plateViolations[i].isPaid;
        }
        
        return (descriptions, fineAmounts, timestamps, paymentStatuses);
    }
}
