(() => {
  const form = document.querySelector('.quit-form');
  if (!form) return;
  form.addEventListener('submit', async (event) => {
    // Preserve the form's existing confirmation dialog.
    if (event.defaultPrevented) return;
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    button.textContent = '正在退出…';
    try {
      const response = await fetch('/quit', {
        method: 'POST', headers: {'Accept': 'application/json'}, cache: 'no-store',
        credentials: 'same-origin'
      });
      if (!response.ok) throw new Error(`退出请求失败（${response.status}）`);
      let acknowledged=false;
      try { acknowledged=JSON.parse(await response.text())?.status==='shutting_down'; } catch (_) {}
      if(!acknowledged)throw new Error('程序未返回有效的退出确认，请刷新页面后重试。');
      document.title = '已退出 · ClinicalExtractor';
      const main = document.createElement('main');
      const heading = document.createElement('h1');heading.textContent='程序正在退出';
      const note = document.createElement('p');note.textContent='正在自动关闭此页面…';
      const closeButton = document.createElement('button');closeButton.textContent='关闭此页面';
      function closePage() {
        try { window.open('', '_self'); window.close(); } catch (_) {}
        setTimeout(()=>{heading.textContent='程序已退出';note.textContent='浏览器未允许自动关闭，请手动关闭此标签页。';},400);
      }
      closeButton.addEventListener('click',closePage);
      main.append(heading,note,closeButton);document.body.replaceChildren(main);
      setTimeout(closePage,1200);
    } catch (error) {
      button.disabled=false;button.textContent='退出程序';
      alert(error.message || '退出失败，请重试');
    }
  });
})();
