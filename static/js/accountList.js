document.querySelectorAll(".account-row").forEach(row => {
  row.addEventListener("click", () => {

    const branchId = row.dataset.branchId;
    const isAdmin = row.dataset.isAdmin === "true";
    const email = row.dataset.email;
    const name = row.dataset.name;

    Swal.fire({
      title: "계정 권한 변경",
      html: `
        <div class="account-modal">
          <div class="account-info">
            <div><strong>이메일</strong><br>${email}</div>
            <div><strong>이름</strong><br>${name}</div>
          </div>

          <div class="account-role">
            <label>
              <input type="radio" name="role" value="admin" ${isAdmin ? "checked" : ""}>
              관리자
            </label>
            <label>
              <input type="radio" name="role" value="user" ${!isAdmin ? "checked" : ""}>
              일반 사용자
            </label>
          </div>
        </div>
      `,
      showConfirmButton: true,
      confirmButtonText: "저장",
      showCloseButton: true,
      customClass: {
        popup: "pumgo-popup",
        confirmButton: "pumgo-btn-primary"
      },
      preConfirm: () => {
        const selected = document.querySelector('input[name="role"]:checked');
        if (!selected) {
          Swal.showValidationMessage("역할을 선택하세요");
          return false;
        }
        return selected.value;
      }
    }).then(result => {
      if (!result.isConfirmed) return;

      fetch("/admin/accounts/update-role", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          branch_id: branchId,
          is_admin: result.value === "admin"
        })
      })
      .then(res => res.json())
      .then(data => {
        if (!data.success) {
          Swal.fire("오류", data.message, "error");
          return;
        }

        Swal.fire({
          toast: true,
          position: "top-end",
          icon: "success",
          title: "권한이 변경되었습니다",
          showConfirmButton: false,
          timer: 1200
        }).then(() => location.reload());
      });
    });

  });
});
