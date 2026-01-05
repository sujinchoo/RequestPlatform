/* ======================================================
 * Account List JS
 * - Sheet tab switch
 * - Role change (SweetAlert)
 * - Account delete
 * ====================================================== */

document.addEventListener("DOMContentLoaded", () => {

  /* ----------------------------------
   * Sheet Tab 전환 (관리자 / 일반)
   * ---------------------------------- */
  const tabs = document.querySelectorAll(".sheet-tab");
  const panels = document.querySelectorAll(".sheet-panel");

  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.sheet; // admin | user

      // active 초기화
      tabs.forEach(t => t.classList.remove("active"));
      panels.forEach(p => p.classList.remove("active"));

      // 선택 탭 활성화
      tab.classList.add("active");
      document.getElementById(`sheet-${target}`).classList.add("active");
    });
  });


  /* ----------------------------------
   * 계정 ROW 클릭 → 권한 변경
   * ---------------------------------- */
  document.querySelectorAll(".account-row").forEach(row => {
    row.addEventListener("click", (e) => {

      // ❌ 삭제 버튼 클릭 시 row 이벤트 차단
      if (e.target.classList.contains("btn-delete")) return;

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

            <div class="account-modal-actions">
              <button type="button" class="pumgo-btn-primary">
                저장
              </button>
            </div>

          </div>
        `,
        showConfirmButton: false,
        showCloseButton: true,
        focusConfirm: false,
        customClass: { popup: "pumgo-popup" },
        didOpen: () => {
          const saveBtn = Swal.getPopup().querySelector(".pumgo-btn-primary");

          saveBtn.addEventListener("click", () => {
            const selected = Swal.getPopup().querySelector(
              'input[name="role"]:checked'
            );

            if (!selected) {
              Swal.showValidationMessage("역할을 선택하세요");
              return;
            }

            const newRoleIsAdmin = selected.value === "admin";

            fetch("/admin/accounts/update-role", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                branch_id: branchId,
                is_admin: newRoleIsAdmin
              })
            })
            .then(res => res.json())
            .then(data => {
              if (!data.success) {
                Swal.fire("오류", data.message || "권한 변경 실패", "error");
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
            })
            .catch(() => {
              Swal.fire("오류", "서버 통신 오류", "error");
            });
          });
        }
      });
    });
  });


  /* ----------------------------------
   * 삭제 버튼 클릭 → 계정 삭제
   * ---------------------------------- */
  document.querySelectorAll(".btn-delete").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation(); // ⭐ row 클릭 이벤트 차단

      const row = btn.closest(".account-row");
      const branchId = row.dataset.branchId;
      const email = row.dataset.email;

      Swal.fire({
        title: "계정 삭제",
        html: `
          <b>${email}</b><br>
          해당 계정을 삭제하시겠습니까?<br><br>
          <span style="color:#dc2626;font-weight:600">
            삭제 후 복구할 수 없습니다.
          </span>
        `,
        icon: "warning",
        showCancelButton: true,
        confirmButtonText: "삭제",
        cancelButtonText: "취소",
        confirmButtonColor: "#dc2626",
        cancelButtonColor: "#6b7280"
      }).then(result => {
        if (!result.isConfirmed) return;

        fetch("/admin/accounts/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ branch_id: branchId })
        })
        .then(res => res.json())
        .then(data => {
          if (!data.success) {
            Swal.fire("오류", data.message || "삭제 실패", "error");
            return;
          }

          Swal.fire({
            toast: true,
            position: "top-end",
            icon: "success",
            title: "계정이 삭제되었습니다",
            showConfirmButton: false,
            timer: 1200
          }).then(() => location.reload());
        })
        .catch(() => {
          Swal.fire("오류", "서버 통신 오류", "error");
        });
      });
    });
  });

});
